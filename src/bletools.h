#ifndef BLETOOLS_H
#define BLETOOLS_H

#include <vector>
#include <stdint.h>
#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEAdvertising.h>
#include "BLETools.h"
#include "Fastcondevice.h"

//#include "bcble.h"

#define USE_DEFAULT_BLE_ADAPTER true

const std::vector<uint8_t> DEFAULT_ENCRYPT_KEY = {0x5e, 0x36, 0x7b, 0xc4};
// const u_int8_t DEFAULT_BLE_FASTCON_ADDRESS[3] = {0xC1, 0xC2, 0xC3};

const std::vector<uint8_t> BLE_PREDATA = {0x02, 0x01, 0x02, 0x1b, 0xff, 0xf0, 0xff};

static uint8_t scan_rsp_data[] = {
    0x02, 0x01, 0x04,
    0x02, 0x0a, 0xeb,
    0x16, 0x09, 'E', 'S', 'P', '_', 'M', 'U', 'L', 'T', 'I', '_', 'A',
    'D', 'V', '_', 'L', 'E', 'G', 'A', 'C', 'Y', 0X0};


//const std::vector<uint8_t> PHONE_KEY = {0x38, 0x35, 0x36, 0x30};
const std::vector<uint8_t> DEFAULT_BLE_FASTCON_ADDRESS = {0xC1, 0xC2, 0xC3};
const u32_t BLE_CMD_RETRY_CNT = 1;
const u32_t BLE_CMD_SEND_TIME = 3000; // PathInterpolatorCompat.MAX_NUM_POINTS;
// const u32_t BLE_CMD_ADVERTISE_LENGTH = 3000; // how long, in ms, to advertise for a command
const int BLE_CMD_ADVERTISE_LENGTH = 3000;


struct WhiteningContext
{
    uint32_t f_0x0;
    uint32_t f_0x4;
    uint32_t f_0x8;
    uint32_t f_0xc;
    uint32_t f_0x10;
    uint32_t f_0x14;
    uint32_t f_0x18;
};

boolean sendCommand(
    u_int8_t i,
    byte data[12],
    byte key[4],
    u_int32_t retry_count,
    u_int32_t send_time,
    bool forward,
    bool use_default_adapter,
    bool use_22_data,
    u_int8_t i2);

std::vector<uint8_t> do_generate_command(
    uint8_t i,
    const std::vector<uint8_t> &data,
    std::vector<uint8_t> *key,
    int32_t _retry_count,
    int32_t _send_interval,
    bool forward,
    bool use_default_adapter,
    bool use_22_data,
    uint8_t i2);

std::vector<uint8_t> command_with_delay_impl(
    uint8_t n,
    const std::vector<uint8_t> &data,
    std::vector<uint8_t> *key,
    int retry_count,
    int send_interval,
    bool forward,
    int delay,
    bool use_default_adapter,
    bool use_22_data,
    uint8_t i2);

std::vector<uint8_t> command_with_no_delay(
    uint8_t i,
    const std::vector<uint8_t> &data,
    std::vector<uint8_t> *key,
    int retry_count,
    int send_time,
    bool forward,
    bool use_default_adapter,
    bool use_22_data,
    uint8_t i2);

std::vector<uint8_t> command_with_delay(
    uint8_t i,
    const std::vector<uint8_t> &data,
    std::vector<uint8_t> *key,
    int retry_count,
    int send_time,
    bool forward,
    int delay,
    bool use_default_adapter,
    bool use_22_data,
    uint8_t i2);

std::vector<uint8_t> single_control(uint32_t addr, const std::vector<uint8_t> &key, const std::vector<uint8_t> &data, int delay);
std::vector<uint8_t> single_control_nodelay(uint32_t addr, std::vector<uint8_t> *key, const  std::vector<uint8_t> &data);
std::vector<uint8_t> command_start_scan();
std::vector<uint8_t> get_rf_payload(const std::vector<uint8_t> &addr, const std::vector<uint8_t> &data);
void whitening_init(uint32_t val, WhiteningContext *ctx);
void whitening_encode(std::vector<uint8_t> &data, WhiteningContext *ctx);


std::vector<uint8_t> package_ble_fastcon_body(
    uint8_t i,
    uint8_t i2,
    uint32_t sequence,
    uint8_t safe_key,
    bool forward,
    const std::vector<uint8_t> &data,
    const std::vector<uint8_t> &key);

std::vector<uint8_t> get_payload_with_inner_retry(
    uint8_t i,
    const std::vector<uint8_t> &data,
    uint8_t i2,
    std::vector<uint8_t> *key,
    bool forward,
    bool use_22_data);

void fastcon_ble_encrypt(const u8_t *src, u8_t *dst, size_t size, const u8_t *key);
void fastcon_ble_header_encrypt(const u8_t *src, u8_t *dst, size_t data_len);
void sendAdvertise(std::vector<uint8_t> scancmd);
FastconDevice parse_ble_broadcast(uint8_t *data, size_t data_len, uint8_t phone_key[4]); //> Option<BroadcastType>

#endif