/*
 * ESP-NOW POI Firmware for Open Pixel Poi (ESP32-C3)
 *
 * Receives a continuous pixel stream via ESP-NOW from a sender (laptop app).
 * Displays on WS2812 LED strip. Button enters light sleep;
 * next press wakes the device and resumes streaming.
 * Device group bitmask filtering allows targeting specific devices.
 *
 * ESP-NOW Packet Format (max 250 bytes):
 *   [0]       uint8_t   type            = 0x01 (pixel stream)
 *   [1-2]     uint16_t  group_mask      bitmask: bit N = group N
 *   [3]       uint8_t   frame_count     number of frames in this packet
 *   [4]       uint8_t   pixels_per_frame LEDs per frame (e.g. 20, 14, ...)
 *   [5..249]  uint8_t   data[]          frame_count * pixels_per_frame * 3
 *
 * Header = 5 bytes. Max frames/packet = floor((250 - 5) / (px * 3)).
 * Sender broadcasts on WiFi channel 1 with ESP-NOW.
 */

#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "esp_now.h"
#include "esp_log.h"
#include "esp_event.h"
#include "nvs_flash.h"
#include "driver/gpio.h"
#include "esp_sleep.h"
#include "led_strip.h"

static const char *TAG = "poi_espnow";

/* ------------------------------------------------------------------ */
/* Configuration                                                       */
/* ------------------------------------------------------------------ */

#define WIFI_CHANNEL    1
#define DEVICE_GROUP_ID 3

#define LED_GPIO        6
#define BUTTON_GPIO     3
#define REGULATOR_GPIO  GPIO_NUM_20
#define MAX_LEDS        20
#define PIXEL_BUF_BYTES (MAX_LEDS * 3)

#define PKT_TYPE_PIXEL  0x01
#define PKT_HDR_SIZE    5
#define PKT_MAX_SIZE    250

/* ------------------------------------------------------------------ */
/* Packet structure                                                    */
/* ------------------------------------------------------------------ */

typedef struct __attribute__((packed)) {
    uint8_t  type;
    uint16_t group_mask;
    uint8_t  frame_count;
    uint8_t  pixels_per_frame;
    uint8_t  data[];
} pixel_pkt_t;

/* ------------------------------------------------------------------ */
/* State                                                               */
/* ------------------------------------------------------------------ */

static led_strip_handle_t s_strip;

static uint8_t       s_frame[2][PIXEL_BUF_BYTES]; /* double-buffer latch */
static uint8_t       s_frame_px[2];
static uint8_t       s_active;
static uint32_t      s_version;
static SemaphoreHandle_t s_mux;

static volatile bool s_btn_flag = false;

static volatile uint32_t s_rx_ok, s_rx_grp;
static volatile uint32_t s_played, s_repeated;

/* ------------------------------------------------------------------ */
/* Forward declarations                                                */
/* ------------------------------------------------------------------ */

static void startup_animation(void);

/* ------------------------------------------------------------------ */
/* Latest-frame latch (double-buffered, mutex-protected)               */
/*                                                                     */
/* A FIFO buys nothing for ESP-NOW POV: over-the-air loss can't be     */
/* buffered back, and on overflow a FIFO either drops-oldest (growing  */
/* lag, wrong angle for a spinning POV) or drops-newest (same as a     */
/* latch). This holds exactly the latest frame; the writer always      */
/* fills the buffer the reader isn't copying, and the swap happens     */
/* under the same lock, so no tearing and lag is bounded at one frame. */
/* ------------------------------------------------------------------ */

static void latch_init(void)
{
    s_mux = xSemaphoreCreateMutex();
    s_active = 0;
    s_version = 0;
    memset(s_frame, 0, sizeof(s_frame));
    memset(s_frame_px, 0, sizeof(s_frame_px));
}

static void latch_publish(const uint8_t *data, uint8_t px)
{
    if (xSemaphoreTake(s_mux, pdMS_TO_TICKS(2)) != pdTRUE) return;
    uint8_t w = 1 - s_active;
    memcpy(s_frame[w], data, px * 3);
    s_frame_px[w] = px;
    s_active = w;
    s_version++;
    xSemaphoreGive(s_mux);
}

/* Returns the version after the read; the caller compares it against its
   cached version to tell "new frame" from "repeat last". */
static uint32_t latch_read(uint8_t *dst, uint8_t *px_out)
{
    uint32_t v = s_version;
    if (xSemaphoreTake(s_mux, pdMS_TO_TICKS(1)) == pdTRUE) {
        uint8_t a = s_active;
        *px_out = s_frame_px[a];
        memcpy(dst, s_frame[a], (*px_out) * 3);
        v = s_version;
        xSemaphoreGive(s_mux);
    }
    return v;
}

static uint32_t latch_version(void)
{
    uint32_t v;
    if (xSemaphoreTake(s_mux, pdMS_TO_TICKS(1)) != pdTRUE) return s_version;
    v = s_version;
    xSemaphoreGive(s_mux);
    return v;
}

/* ------------------------------------------------------------------ */
/* ESP-NOW receive callback                                            */
/* ------------------------------------------------------------------ */

static void on_espnow_recv(const esp_now_recv_info_t *info,
                           const uint8_t *data, int len)
{
    if (len < PKT_HDR_SIZE) return;

    const pixel_pkt_t *p = (const pixel_pkt_t *)data;
    if (p->type != PKT_TYPE_PIXEL) return;
    if (!(p->group_mask & (1U << DEVICE_GROUP_ID))) { s_rx_grp++; return; }

    uint8_t px_src = p->pixels_per_frame;      /* stride between frames */
    if (px_src == 0) return;

    uint8_t cnt = p->frame_count;
    uint32_t stride = px_src * 3U;
    uint32_t max_frames = (PKT_MAX_SIZE - PKT_HDR_SIZE) / stride;
    if (cnt == 0 || cnt > max_frames) return;
    if (len < PKT_HDR_SIZE + cnt * stride) return;

    /* Trim to this strip's own length instead of rejecting the packet, so a
       sender can broadcast one 20px frame to every strip (14/20/10 LEDs). */
    uint8_t px = (px_src > MAX_LEDS) ? MAX_LEDS : px_src;
    for (uint8_t i = 0; i < cnt; i++)
        latch_publish(p->data + i * stride, px);
    s_rx_ok++;
}

/* ------------------------------------------------------------------ */
/* Init helpers                                                        */
/* ------------------------------------------------------------------ */

static void wifi_init(void)
{
    esp_err_t r = nvs_flash_init();
    if (r == ESP_ERR_NVS_NO_FREE_PAGES || r == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ESP_ERROR_CHECK(nvs_flash_init());
    }
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE));
    ESP_LOGI(TAG, "WiFi ch%d", WIFI_CHANNEL);
}

static void espnow_init(void)
{
    ESP_ERROR_CHECK(esp_now_init());
    ESP_ERROR_CHECK(esp_now_register_recv_cb(on_espnow_recv));
    ESP_LOGI(TAG, "ESP-NOW ready");
}

static void wifi_espnow_restart(void)
{
    esp_wifi_stop();
    esp_wifi_start();
    esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);
    esp_now_init();
    esp_now_register_recv_cb(on_espnow_recv);
    ESP_LOGI(TAG, "WiFi+ESP-NOW restarted");
}

static void strip_init(void)
{
    led_strip_config_t sc = {
        .strip_gpio_num = LED_GPIO,
        .max_leds = MAX_LEDS,
        .color_component_format = LED_STRIP_COLOR_COMPONENT_FMT_GRB,
        .led_model = LED_MODEL_WS2812,
    };
    led_strip_rmt_config_t rc = {
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = 10 * 1000 * 1000,
        .mem_block_symbols = 128,
    };
    ESP_ERROR_CHECK(led_strip_new_rmt_device(&sc, &rc, &s_strip));
    led_strip_clear(s_strip);
    ESP_LOGI(TAG, "Strip %d LEDs GPIO%d", MAX_LEDS, LED_GPIO);
}

/* ------------------------------------------------------------------ */
/* Button (press = light sleep, wake on next press)                    */
/* ------------------------------------------------------------------ */

static void IRAM_ATTR btn_isr(void *arg) { s_btn_flag = true; }

static void btn_init(void)
{
    gpio_config_t c = {
        .pin_bit_mask = 1ULL << BUTTON_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .intr_type = GPIO_INTR_ANYEDGE,
    };
    gpio_config(&c);
    gpio_install_isr_service(ESP_INTR_FLAG_IRAM);
    gpio_isr_handler_add(BUTTON_GPIO, btn_isr, NULL);
}

/* ------------------------------------------------------------------ */
/* Shutdown animation (red blink)                                      */
/* ------------------------------------------------------------------ */

static void shutdown_animation(void)
{
    for (int blink = 0; blink < 3; blink++) {
        for (int j = 0; j < MAX_LEDS; j++)
            led_strip_set_pixel(s_strip, j, 80, 0, 0);
        led_strip_refresh(s_strip);
        vTaskDelay(pdMS_TO_TICKS(200));
        led_strip_clear(s_strip);
        vTaskDelay(pdMS_TO_TICKS(200));
    }
}

static void enter_light_sleep(void)
{
    uint32_t waited = 0;

    /* Wait for button release so wake-on-press doesn't trigger immediately */
    while ((gpio_get_level(BUTTON_GPIO) == 0) && (waited < 2000)) {
        vTaskDelay(pdMS_TO_TICKS(50));
        waited += 50;
    }
    vTaskDelay(pdMS_TO_TICKS(50));

    shutdown_animation();
    led_strip_clear(s_strip);
    ESP_LOGI(TAG, "Entering light sleep...");

    /* Kill the 5V rail so the strip + board regulators don't eat the battery */
    gpio_set_level(REGULATOR_GPIO, 0);
    vTaskDelay(pdMS_TO_TICKS(100));

    /* Radio off guarantees the WiFi/MAC-BB power domain can fully power down */
    esp_wifi_stop();

    /* Keep the button pulled HIGH during light sleep. The normal pad pull-up
       lives in the powered-down digital domain on ESP32-C3, so without this
       the pin floats LOW and the LOW_LEVEL wake source fires immediately. */
    gpio_sleep_set_direction(BUTTON_GPIO, GPIO_MODE_INPUT);
    gpio_sleep_set_pull_mode(BUTTON_GPIO, GPIO_PULLUP_ONLY);

    gpio_wakeup_enable(BUTTON_GPIO, GPIO_INTR_LOW_LEVEL);
    esp_sleep_enable_gpio_wakeup();
    esp_light_sleep_start();

    /* Woke up. Restore ANYEDGE interrupt type (gpio_wakeup changed it). */
    gpio_config_t wake_btn = {
        .pin_bit_mask = (1ULL << BUTTON_GPIO),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .intr_type = GPIO_INTR_ANYEDGE,
    };
    gpio_config(&wake_btn);

    /* Consume the wake-up press (bounded so we can never hang here) */
    waited = 0;
    while ((gpio_get_level(BUTTON_GPIO) == 0) && (waited < 2000)) {
        vTaskDelay(pdMS_TO_TICKS(50));
        waited += 50;
    }
    vTaskDelay(pdMS_TO_TICKS(50));
    s_btn_flag = false;

    /* Power the 5V rail back on before anything else lights up */
    gpio_set_level(REGULATOR_GPIO, 1);

    /* Restart WiFi and ESP-NOW (radio was suspended during light sleep) */
    wifi_espnow_restart();

    ESP_LOGI(TAG, "Woke up");
    startup_animation();
}

/* ------------------------------------------------------------------ */
/* LED render task                                                     */
/* ------------------------------------------------------------------ */

static void render_task(void *arg)
{
    uint8_t fr[PIXEL_BUF_BYTES];
    uint8_t px;
    uint32_t last_ver = 0;
    ESP_LOGI(TAG, "Render task started");

    for (;;) {
        /* Button check (runs in same task as render — no race) */
        if (s_btn_flag) {
            s_btn_flag = false;
            vTaskDelay(pdMS_TO_TICKS(50));
            if (!gpio_get_level(BUTTON_GPIO))
                enter_light_sleep();
        }

        uint32_t ver = latch_read(fr, &px);
        if (ver != last_ver) {
            last_ver = ver;
            s_played++;
        } else {
            s_repeated++;
            vTaskDelay(pdMS_TO_TICKS(1)); /* let idle run when no inbound frames */
        }

        for (int i = 0; i < px; i++)
            led_strip_set_pixel(s_strip, i,
                                fr[i * 3], fr[i * 3 + 1], fr[i * 3 + 2]);
        led_strip_refresh(s_strip);

        taskYIELD();
    }
}

/* ------------------------------------------------------------------ */
/* Startup animation (rainbow fade)                                    */
/* ------------------------------------------------------------------ */

static void hsv_to_rgb(uint8_t h, uint8_t s, uint8_t v,
                       uint8_t *r, uint8_t *g, uint8_t *b)
{
    if (s == 0) { *r = *g = *b = v; return; }
    uint8_t region = h / 43;
    uint8_t remain = (h - region * 43) * 6;
    uint8_t p = (v * (255 - s)) >> 8;
    uint8_t q = (v * (255 - ((s * remain) >> 8))) >> 8;
    uint8_t t = (v * (255 - ((s * (255 - remain)) >> 8))) >> 8;
    switch (region) {
    case 0:  *r = v; *g = t; *b = p; break;
    case 1:  *r = q; *g = v; *b = p; break;
    case 2:  *r = p; *g = v; *b = t; break;
    case 3:  *r = p; *g = q; *b = v; break;
    case 4:  *r = t; *g = p; *b = v; break;
    default: *r = v; *g = p; *b = q; break;
    }
}

static void startup_animation(void)
{
    ESP_LOGI(TAG, "Startup rainbow fade...");
    uint32_t ms = 3000;
    uint32_t frames = ms / 20;
    for (uint32_t i = 0; i < frames; i++) {
        uint8_t hue = (i * 256) / frames;
        uint8_t r, g, b;
        hsv_to_rgb(hue, 255, 80, &r, &g, &b);
        for (int j = 0; j < MAX_LEDS; j++)
            led_strip_set_pixel(s_strip, j, r, g, b);
        led_strip_refresh(s_strip);
        vTaskDelay(pdMS_TO_TICKS(20));
    }
    led_strip_clear(s_strip);
}

/* ------------------------------------------------------------------ */
/* Entry point                                                         */
/* ------------------------------------------------------------------ */

void app_main(void)
{
    ESP_LOGI(TAG, "ESP-NOW POI starting  group=%d", DEVICE_GROUP_ID);

    /* Enable the 5V rail before anything powers up */
    gpio_set_direction(REGULATOR_GPIO, GPIO_MODE_OUTPUT);
    gpio_set_level(REGULATOR_GPIO, 1);

    latch_init();
    wifi_init();
    espnow_init();
    strip_init();
    startup_animation();
    btn_init();

    xTaskCreate(render_task, "render", 4096, NULL, 5, NULL);

    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(5000));
ESP_LOGI(TAG, "rx:%lu grp:%lu play:%lu rep:%lu ver:%lu",
             s_rx_ok, s_rx_grp, s_played, s_repeated, latch_version());
    }
}
