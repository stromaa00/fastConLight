#include "bletools.h"
#include "tools.h"
#include "FastconDevice.h"
#include <stdexcept>


BLEMultiAdvertising adv(4); // max number of advertisement data

const static uint8_t adv_data[] = {
    0x02, 0x01, 0x02, 0x1b, 0xff, 0xf0, 0xff,
    0x6d, 0xb6, 0x43, 0x68, 0x93, 0x1d, 0xdd, 0x4a, 0x91, 0x8b, 0x8f, 0x3a, 0x97, 0xf9, 0x0e, 0xcc, 0x42, 0x91, 0xc1, 0x65, 0x5b, 0xfd, 0xda, 0x0};


esp_ble_gap_ext_adv_params_t adv_params = {
    .type = ESP_BLE_LEGACY_ADV_TYPE_IND,
    .interval_min = 0x45,
    .interval_max = 0x45,
    .channel_map = ADV_CHNL_ALL,
    .own_addr_type = BLE_ADDR_TYPE_RANDOM,
    .filter_policy = ADV_FILTER_ALLOW_SCAN_ANY_CON_ANY,
    .primary_phy = ESP_BLE_GAP_PHY_1M,
    .max_skip = 0,
    .secondary_phy = ESP_BLE_GAP_PHY_1M,
    .sid = 2,
    .scan_req_notif = false,
};

uint8_t addr_legacy[6] = {0xc0, 0xde, 0x52, 0x00, 0x00, 0x03};


std::vector<uint8_t> do_generate_command(
    uint8_t i,
    const std::vector<uint8_t> &data,
    std::vector<uint8_t> *key,
    int32_t _retry_count,
    int32_t _send_interval,
    bool forward,
    bool use_default_adapter,
    bool use_22_data,
    uint8_t i2)
{
   // Serial.println("do_generate_command");
    // TODO: handle retry_count and send_interval
    if (use_22_data)
    {
        // TODO: Handle use_22_data case
        // You can provide the necessary implementation here
        
        // or return an error or default value as per your requirement.
        // For now, we'll throw an exception indicating unimplemented behavior.
        Serial.println("std::runtime_error(Use case for use_22_data is not implemented.");
        throw std::runtime_error("Use case for use_22_data is not implemented.");
    }

    if (!use_default_adapter)
    {
        // TODO: Handle non-default adapter case
        // You can provide the necessary implementation here
        // or return an error or default value as per your requirement.
        // For now, we'll throw an exception indicating unimplemented behavior.
        Serial.println("throw std::runtime_error(Use case for non-default adapter is not implemented.");
        throw std::runtime_error("Use case for non-default adapter is not implemented.");
    }

    i2 = std::max(i2, static_cast<uint8_t>(0));
    Serial.println("do_generate_command:  i: " + String(i) + " data: " + bytevector_2_str(data) ); //+ " key: "+bytevector_2_str(key));
    std::vector<uint8_t> payload = get_payload_with_inner_retry(i, data, i2, key, forward, use_22_data);
    
    Serial.println("do_generate_command: get_payload_with_inner_retry : " + String(i) + " payload: " + bytevector_2_str(payload));

    payload = get_rf_payload(DEFAULT_BLE_FASTCON_ADDRESS, payload);

    WhiteningContext context;
    whitening_init(0x25, &context);
    whitening_encode(payload, &context);

    return std::vector<uint8_t>(payload.begin() + 0xf, payload.end()); // drop the first 0xf bytes
}



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
    uint8_t i2)
{
    Serial.println("command_with_delay_impl");
    if (delay <= 0)
    {
        return do_generate_command(
            n,
            data,
            key,
            retry_count,
            send_interval,
            forward,
            use_default_adapter,
            use_22_data,
            i2);
    }
    else
    {
        throw std::runtime_error("delay not implemented");
    }
}

std::vector<uint8_t> command_with_no_delay(
    uint8_t i,
    const std::vector<uint8_t> &data,
    std::vector<uint8_t> *key,
    int retry_count,
    int send_time,
    bool forward,
    bool use_default_adapter,
    bool use_22_data,
    uint8_t i2)
{
    Serial.println("command_with_no_delay");
    return command_with_delay_impl(
        i,
        data,
        key,
        retry_count,
        send_time,
        forward,
        0,
        use_default_adapter,
        use_22_data,
        i2);
}

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
    uint8_t i2)
{
    return command_with_delay_impl(
        i,
        data,
        key,
        retry_count,
        send_time,
        forward,
        delay,
        use_default_adapter,
        use_22_data,
        i2);
}

std::vector<uint8_t> single_control(uint32_t addr, std::vector<uint8_t> *key, const std::vector<uint8_t> &data, int delay)
{
    std::vector<uint8_t> result_data(12, 0);

    result_data[0] = 2 | (((0xfffffff & (data.size() + 1)) << 4) & 0xFF);
    result_data[1] = addr & 0xFF;
    std::copy(data.begin(), data.end(), result_data.begin() + 2);

    return command_with_delay(
        5,
        result_data,
        key,
        BLE_CMD_RETRY_CNT,
        BLE_CMD_ADVERTISE_LENGTH,
        true,
        delay,
        true,
        addr > 256,
        static_cast<uint8_t>(addr / 256));
}

std::vector<uint8_t> single_control_nodelay(uint32_t addr, std::vector<uint8_t> *key, const std::vector<uint8_t> &data)
{
    return single_control(addr, key, data, 0);
}



std::vector<uint8_t> command_start_scan()
{
    Serial.println("command_start_scan");
    return command_with_no_delay(
        0,
        {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},
        nullptr,
        BLE_CMD_RETRY_CNT,
        -1,
        false,
        USE_DEFAULT_BLE_ADAPTER,
        false,
        0);
}

std::vector<uint8_t> get_rf_payload(const std::vector<uint8_t> &addr, const std::vector<uint8_t> &data)
{
  
    const int data_offset = 0x12;
    const int inverse_offset = 0x0f;
    const int result_data_size = data_offset + addr.size() + data.size();
    std::vector<uint8_t> resultbuf(result_data_size + 2, 0);

    // some hardcoded values
    resultbuf[0x0f] = 0x71;
    resultbuf[0x10] = 0x0f;
    resultbuf[0x11] = 0x55;

    // reverse copy the address
    for (size_t i = 0; i < addr.size(); i++)
    {
        resultbuf[data_offset + addr.size() - i - 1] = addr[i];
    }

    std::copy(data.begin(), data.end(), resultbuf.begin() + data_offset + addr.size());

    for (int i = inverse_offset; i < inverse_offset + addr.size() + 3; i++)
    {
        resultbuf[i] = reverse_8(resultbuf[i]);
    }

    uint16_t crc = crc16(addr, data);
    resultbuf[result_data_size] = static_cast<uint8_t>(crc);
    resultbuf[result_data_size + 1] = static_cast<uint8_t>(crc >> 8);
    return resultbuf;
}

void whitening_init(uint32_t val, WhiteningContext *ctx)
{
    uint32_t v0[4] = {(val >> 5), (val >> 4), (val >> 3), (val >> 2)};

    ctx->f_0x0 = 1;
    ctx->f_0x4 = v0[0] & 1;
    ctx->f_0x8 = v0[1] & 1;
    ctx->f_0xc = v0[2] & 1;
    ctx->f_0x10 = v0[3] & 1;
    ctx->f_0x14 = (val >> 1) & 1;
    ctx->f_0x18 = val & 1;
}

void whitening_encode(std::vector<uint8_t> &data, WhiteningContext *ctx)
{
    for (size_t i = 0; i < data.size(); ++i)
    {
        uint32_t varC = ctx->f_0xc;
        uint32_t var14 = ctx->f_0x14;
        uint32_t var18 = ctx->f_0x18;
        uint32_t var10 = ctx->f_0x10;
        uint32_t var8 = var14 ^ ctx->f_0x8;
        uint32_t var4 = var10 ^ ctx->f_0x4;
        uint32_t _var = var18 ^ varC;
        uint32_t var0 = _var ^ ctx->f_0x0;

        uint8_t c = data[i];
        data[i] = ((c & 0x80) ^ ((var8 ^ var18) << 7)) + ((c & 0x40) ^ (var0 << 6)) + ((c & 0x20) ^ (var4 << 5)) + ((c & 0x10) ^ (var8 << 4)) + ((c & 0x08) ^ (_var << 3)) + ((c & 0x04) ^ (var10 << 2)) + ((c & 0x02) ^ (var14 << 1)) + ((c & 0x01) ^ (var18 << 0));

        ctx->f_0x8 = var4;
        ctx->f_0xc = var8;
        ctx->f_0x10 = var8 ^ varC;
        ctx->f_0x14 = var0 ^ var10;
        ctx->f_0x18 = var4 ^ var14;
        ctx->f_0x0 = var8 ^ var18;
        ctx->f_0x4 = var0;
    }
}

std::vector<uint8_t> package_ble_fastcon_body(
    uint8_t i,
    uint8_t i2,
    uint32_t sequence,
    uint8_t safe_key,
    bool forward,
    const std::vector<uint8_t> &data,
    std::vector<uint8_t> *key)
{
    //Serial.println("package_ble_fastcon_body");
    // bit 7 is forward
    // bit 6-4 is i2
    // bit 3-0 is i
    std::vector<uint8_t> body(data.size() + 4, 0);
    body[0] = ((i2 & 0b1111) << 0) | ((i & 0b111) << 4) | (static_cast<uint8_t>(forward) << 7);
    body[1] = static_cast<uint8_t>(sequence);
    body[2] = safe_key;
    body[3] = 0; // checksum

    std::copy(data.begin(), data.end(), body.begin() + 4);

    uint8_t checksum = 0;
    for (size_t cnt = 0; cnt < body.size(); ++cnt)
    {
        if (cnt == 3)
        {
            continue; // skip checksum itself
        }

        // allow overflow
        checksum = static_cast<uint8_t>(checksum + body[cnt]);
    }

    body[3] = checksum;

    for (size_t i = 0; i < 4; ++i)
    {
        body[i] = DEFAULT_ENCRYPT_KEY[i & 3] ^ body[i];
    }

    const std::vector<uint8_t> &real_key = key != nullptr ? *key : DEFAULT_ENCRYPT_KEY;
    for (size_t i = 0; i < data.size(); ++i)
    {
        body[4 + i] = real_key[i & 3] ^ body[4 + i];
    }

    return body;
}

std::vector<uint8_t> get_payload_with_inner_retry(
    uint8_t i,
    const std::vector<uint8_t> &data,
    uint8_t i2,
    std::vector<uint8_t> *key,
    bool forward,
    bool use_22_data)
{
   // Serial.println("get_payload_with_inner_retry");
    static uint32_t SEND_SEQ = 0;
    static int32_t SEND_COUNT = 0;

    if (SEND_SEQ == 0)
    {
        // auto now = std::chrono::system_clock::now();
        // auto duration = now.time_since_epoch();
        // auto millis = std::chrono::duration_cast<std::chrono::milliseconds>(duration).count();
        // SEND_SEQ = static_cast<uint32_t>(millis) % 256;
    }

    int32_t send_cnt = SEND_COUNT;
    uint8_t some_sequence;

    if (send_cnt >= 5 || i2 <= 1)
    {
        uint32_t next = SEND_SEQ + 1;
        SEND_SEQ = next;
        if (next == 0 || next == 256)
        {
            SEND_SEQ = 1; // reset sequence
        }
        some_sequence = SEND_SEQ;
    }
    else
    {
        some_sequence = (SEND_SEQ + 10) % 255;
    }


    uint8_t safe_key = (key != nullptr) ? (*key)[3] : 255;

    if (use_22_data)
    {
        // TODO: Handle use_22_data case
        // You can provide the necessary implementation here
        // or return an error or default value as per your requirement.
        // For now, we'll throw an exception indicating unimplemented behavior.
        throw std::runtime_error("Use case for use_22_data is not implemented.");
    }
    else
    {
        return package_ble_fastcon_body(i, i2, some_sequence, safe_key, forward, data, key);
    }
}

void fastcon_ble_encrypt(const u8_t *src, u8_t *dst, size_t size, const u8_t *key)
{
       Serial.println("fastcon_ble_encrypt Phone key : " + String(size));
    for (size_t i = 0; i < size; i++)
        dst[i] = key[i & 3] ^ src[i];
}

void fastcon_ble_header_encrypt(const u8_t *src, u8_t *dst, size_t data_len)
{
    for (int i = 0; i < data_len; i++)
        dst[i] = ::DEFAULT_ENCRYPT_KEY[i & 3] ^ src[i];
}


boolean sendCommand(
    u_int8_t i,
    char data[12],
    char key[4],
    u_int32_t retry_count,
    u_int32_t send_time,
    bool z,
    bool use_default_adapter,
    bool use_22_data,
    u_int8_t i2)
{
    adv.setAdvertisingParams(0, &adv_params);
    adv.setAdvertisingData(0, sizeof(adv_data), &adv_data[0]);
    adv.setScanRspData(0, sizeof(scan_rsp_data), &scan_rsp_data[0]);
    adv.setInstanceAddress(0, addr_legacy);
    adv.setDuration(0, 50, 10);
    adv.start(1, 0);
    Serial.println("sendCommand : Data :" +  byte_2_str(data,12) + " key: " + byte_2_str(key,4));
    return true;
}


void sendAdvertise(std::vector<uint8_t> scancmd)
{
    scancmd.insert(scancmd.begin(), BLE_PREDATA.begin(), BLE_PREDATA.end());
    
    adv.setAdvertisingParams(0, &adv_params);
    adv.setAdvertisingData(0, sizeof(adv_data), &adv_data[0]);
    adv.setAdvertisingData(0, scancmd.size(), scancmd.data());
    adv.setScanRspData(0, sizeof(scan_rsp_data), &scan_rsp_data[0]);
    adv.setInstanceAddress(0, addr_legacy);
    adv.setDuration(0, 50, 10);
    adv.start(1, 0);
    Serial.println("send start done");
}

/**** parse_ble_broadcast *******************************************************************/
FastconDevice parse_ble_broadcast(uint8_t *data, size_t data_len, uint8_t phone_key[4]) //> Option<BroadcastType>
{
    FastconDevice devInfo;
    
    u8_t header[4];
    memcpy(header, data, 4);
    fastcon_ble_header_encrypt(data, header, 4);

    uint8_t high = header[0] & 0xf; // some strange high bits

    // high 3 bits
    switch (header[0] >> 4 & 7)
    {

    case 3:
    {
        // let mut content = source[4..].to_vec(); // skip 4 bytes of header
        uint8_t content[data_len - 4];
        Serial.println("case 3");

        fastcon_ble_encrypt(data + 4, content, data_len - 4, phone_key);

        switch (content[0] & 0xf)
        {
        case 0xb:
            Serial.println("0xb");
            Serial.println("todo: timer upload response");
            // Some(BroadcastType::TimerUploadResponse);
            break;
        case 0x4:
        {
            Serial.println("0x4");

            u_int8_t addr = (uint32_t)data[5] | (*data & 0xf) << 8;
            u_int8_t group_addr = data[6];

            String version = "{" + String(content[3]) + "}.{" +
                             String(content[4]) + "}.{" +
                             String(content[10] | (content[11]) << 8) + "}.{" +
                             String(content[6] | (content[7]) << 8) + "}.{" +
                             String(content[5]) + "}";

            Serial.println("todo: heartbeat: Version : " + version + " addr: " + String(addr) + " group_addr : " + String(group_addr));
        }

        // Some(BroadcastType::HeartBeat(HeartBeat { version, short_addr, group_addr, }))

        break;
        default:
            Serial.println("Unknown content type: {}" + String(content[0] & 0xf));
            break;
        }
        break;
    }

    case 1:
    {      
        // 4E6C7A79 EC0BF10A 52F2 A1A8 5E367BC4
        // Key: 5E367BC4
        // Did: EC0BF10A
        // Name: 52F2
        // Type: A1A8 -> (A8A1)

        
        // 4E6D7BF7 E81656FB 88D5 A1A8 5E367BC4
        // 4E6D7BF7E81656FB
        // Key: 5E367BC4
        // Did: E81656FB
        // Name: 88D5
        // Type: A1A8 -> (A8A1)


        memcpy(devInfo.did, &data[4], 6);  // 6 bytes
        memcpy(devInfo.name, &data[8], 2); // 2 bytes
        memcpy(&devInfo.type, &data[10], 2);
        devInfo.type_val = strtol(byte_2_str(devInfo.type, 2).c_str(), nullptr, 16);
        memcpy(devInfo.key, &data[12], 4);
        memcpy(&devInfo.key_val, &data[12], 4);
        devInfo.deviceType = static_cast<EBLEDeviceTypes>(devInfo.type_val);
        
        return devInfo;
        break;
    }

    default:
        Serial.println("Unknown header type: {}");
    }
    // free(header);
    return FastconDevice();
}

