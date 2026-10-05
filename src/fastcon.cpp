#include  "fastcon.h"

#include "BLEBeacon.h"
#include "BLEServer.h"
#include "tools.h"

const uint8_t default_key[] = { 0x5e, 0x36, 0x7b, 0xc4 };
const int redundancy = 5;  // Repeats sending each command to the lights this many times; BLE broadcasting was flakey  

BLEAdvertising *pAdvertising;  


////////////////////////////////////////////////
// You probably don't need to modify below here
////////////////////////////////////////////////


#define BEACON_UUID "87b99b2c-90fd-11e9-bc42-526af7764f64" // UUID 1 128-Bit (may use linux tool uuidgen or random numbers via https://www.uuidgenerator.net/)

void send(uint8_t* data, uint8_t dataLength);

uint8_t SEND_SEQ = 0;
uint8_t SEND_COUNT = 1;

const uint8_t BLE_CMD_RETRY_CNT = 1;
const uint8_t DEFAULT_BLE_FASTCON_ADDRESS[] = { 0xC1, 0xC2, 0xC3 };
const uint8_t addrLength = 3;


/**
 * @brief Dumps the contents of the given data array.
 *
 * This function prints the hexadecimal representation of the data array
 * to the standard output. The length parameter specifies the number of
 * elements in the data array.
 *
 * @param data Pointer to the data array.
 * @param length Number of elements in the data array.
 */
void dump(const uint8_t* data, int length)
{
  for (int i = 0; i < length; i++)
  {
    printf("%2.2X", data[i]);
  }
}

/**
 * Extracts the first integer found in the given input string.
 *
 * @param inputString The input string from which to extract the integer.
 * @return The first integer found in the input string. If no integer is found, returns 0.
 */
int extractInteger(const char* inputString) {
    int result = -1;  // Default value or error indicator

    // Assuming the format is "somestring %d"
    int numRead = std::sscanf(inputString, "%*s %d", &result);

    // Check if sscanf successfully read an integer
    if (numRead == 1) {
        return result;
    } else {
        // Handle the case where no integer was found
        // You can throw an exception, return an error code, etc.
        return -1;  // Adjust this value based on your error handling strategy
    }
}

/**
 * Packages the BLE FastCon body.
 *
 * This function packages the BLE FastCon body with the given parameters.
 *
 * @param i The first integer parameter.
 * @param i2 The second integer parameter.
 * @param sequence The sequence number.
 * @param safe_key The safe key.
 * @param forward The forward parameter.
 * @param data The data array.
 * @param length The length of the data array.
 * @param key The key array.
 * @param payload The output payload.
 * @return The status code.
 */
uint8_t package_ble_fastcon_body(int i, int i2, uint8_t sequence, uint8_t safe_key, int forward, const uint8_t* data, int length, const uint8_t* key, uint8_t*& payload)
{
  if (length > 12)
  {
    printf("data too long");
    payload = 0;
    return 0;
  }
  log_d("data: "); dump(data, length); log_d("\n");
  uint8_t payloadLength = 4 + 12;
  payload = (uint8_t*)malloc(payloadLength);
  payload[0] = (i2 & 0b1111) << 0 | (i & 0b111) << 4 | (forward & 0xff) << 7;
  payload[1] = sequence & 0xff;
  payload[2] = safe_key;
  payload[3] = 0; // checksum
  // fill payload with zeros
  for (int j = 4; j < payloadLength; j++) 
    payload[j]=0;
  
  memcpy(payload + 4, data, length);

  uint8_t checksum = 0;
  for (int j = 0; j < length + 4; j++) 
  {
    if (j == 3) continue;
    checksum = (checksum + payload[j]) & 0xff;
  }
  payload[3] = checksum;
  for (int j = 0; j < 4; j++) {
    payload[j] = default_key[j & 3] ^ payload[j];
  }
  for (int j = 0; j < 12; j++) {
    payload[4 + j] = my_key[j & 3] ^ payload[4 + j];
  }
  return payloadLength;
}

/**
 * Retrieves the payload with inner retry.
 *
 * This function retrieves the payload with inner retry based on the provided parameters.
 *
 * @param i The first parameter of type int.
 * @param data The pointer to the data array of type uint8_t.
 * @param length The length of the data array.
 * @param i2 The second parameter of type int.
 * @param key The pointer to the key array of type uint8_t.
 * @param forward The forward parameter of type int.
 * @param payload The reference to the pointer of the payload array of type uint8_t.
 * @return The result of type uint8_t.
 */
uint8_t get_payload_with_inner_retry(int i, const uint8_t* data, int length, int i2, const uint8_t* key, int forward, uint8_t*& payload) {
  printf("data: "); dump(data, length); printf("\n");

  SEND_COUNT++;
  SEND_SEQ = SEND_COUNT;
  //uint8_t safe_key = key[3];
  uint8_t safe_key = (key != nullptr) ? (key)[3] : 255;
  Serial.printf("safe_key");
  return package_ble_fastcon_body(i, i2, SEND_SEQ, safe_key, forward, data, length, key, payload);
}

/**
 * @brief Initializes the whitening algorithm with the specified value.
 *
 * This function initializes the whitening algorithm with the given value.
 * The whitening algorithm is used to scramble or unscramble data for security purposes.
 *
 * @param val The value to initialize the whitening algorithm with.
 * @param ctx Pointer to the context of the whitening algorithm.
 */
void whiteningInit(uint8_t val, uint8_t* ctx)
{
  ctx[0] = 1;
  ctx[1] = (val >> 5) & 1;
  ctx[2] = (val >> 4) & 1;
  ctx[3] = (val >> 3) & 1;
  ctx[4] = (val >> 2) & 1;
  ctx[5] = (val >> 1) & 1;
  ctx[6] = val & 1;
}

/**
 * Encodes the given data using whitening algorithm.
 * 
 * @param data The input data to be encoded.
 * @param len The length of the input data.
 * @param ctx The context for the whitening algorithm.
 * @param result The output buffer to store the encoded data.
 */
void whiteningEncode(const uint8_t* data, int len, uint8_t* ctx, uint8_t* result)
{
  memcpy(result, data, len);
  for (int i = 0; i < len; i++) {
    int varC = ctx[3];
    int var14 = ctx[5];
    int var18 = ctx[6];
    int var10 = ctx[4];
    int var8 = var14 ^ ctx[2];
    int var4 = var10 ^ ctx[1];
    int _var = var18 ^ varC;
    int var0 = _var ^ ctx[0];

    int c = result[i];
    result[i] = ((c & 0x80) ^ ((var8 ^ var18) << 7))
      + ((c & 0x40) ^ (var0 << 6))
      + ((c & 0x20) ^ (var4 << 5))
      + ((c & 0x10) ^ (var8 << 4))
      + ((c & 0x08) ^ (_var << 3))
      + ((c & 0x04) ^ (var10 << 2))
      + ((c & 0x02) ^ (var14 << 1))
      + ((c & 0x01) ^ (var18 << 0));

    ctx[2] = var4;
    ctx[3] = var8;
    ctx[4] = var8 ^ varC;
    ctx[5] = var0 ^ var10;
    ctx[6] = var4 ^ var14;
    ctx[0] = var8 ^ var18;
    ctx[1] = var0;
  }
}



/**
 * Calculates the CRC-16 checksum for the given data.
 *
 * @param addr The starting address of the data.
 * @param data The data to calculate the checksum for.
 * @param dataLength The length of the data.
 * @return The calculated CRC-16 checksum.
 */
uint16_t crc16(const uint8_t* addr, const uint8_t* data, uint8_t dataLength)
{
  uint16_t crc = 0xffff;

  for (int8_t i = addrLength - 1; i >= 0; i--) 
  {
    crc ^= addr[i] << 8;
    for (uint8_t ii = 0; ii < 4; ii++) {
      uint16_t tmp = crc << 1;

      if ((crc & 0x8000) !=0)
      {
        tmp ^= 0x1021;
      }

      crc = tmp << 1;
      if ((tmp & 0x8000) != 0)
      {
        crc ^= 0x1021;
      }
    }
  }

  for (uint8_t i = 0; i < dataLength; i++) {
    crc ^= reverse_8(data[i]) << 8;
    for (uint8_t ii = 0; ii < 4; ii++) {
      uint16_t tmp = crc << 1;

      if ((crc & 0x8000) != 0) 
      {
        tmp ^= 0x1021;
      }

      crc = tmp << 1;
      if ((tmp & 0x8000) != 0)
      {
        crc ^= 0x1021;
      }
    }
  }
  crc = ~reverse_16(crc) & 0xffff;
  return crc;
}


/**
 * @brief Retrieves the RF payload from the given address and data.
 *
 * This function takes in the address, data, data length, and a pointer to the RF payload.
 * It retrieves the RF payload from the given address and data and stores it in the provided rfPayload pointer.
 *
 * @param addr The address of the RF payload.
 * @param data The data containing the RF payload.
 * @param dataLength The length of the data.
 * @param[out] rfPayload A pointer to store the retrieved RF payload.
 *
 * @return None.
 */
uint8_t get_rf_payload(const uint8_t* addr, const uint8_t* data, uint8_t dataLength, uint8_t*& rfPayload)
{

  uint8_t data_offset = 0x12;
  uint8_t inverse_offset = 0x0f;
  uint8_t result_data_size = data_offset + addrLength + dataLength+2;
  uint8_t* resultbuf = (uint8_t*)malloc(result_data_size);
  memset(resultbuf, 0, result_data_size);

  resultbuf[0x0f] = 0x71;
  resultbuf[0x10] = 0x0f;
  resultbuf[0x11] = 0x55;


  for (uint8_t j = 0; j < addrLength; j++) {
    resultbuf[data_offset + addrLength - j - 1] = addr[j];
  }

  for (int j = 0; j < dataLength; j++) {
    resultbuf[data_offset + addrLength + j] = data[j];
  }


  for (int i = inverse_offset; i < inverse_offset + addrLength + 3; i++) {
    resultbuf[i] = reverse_8(resultbuf[i]);
  }

  int crc = crc16(addr, data, dataLength);
  resultbuf[result_data_size-2] = crc & 0xff;
  resultbuf[result_data_size-1] = (crc >> 8) & 0xff;
  rfPayload = resultbuf;
  return result_data_size;
}

/**
 * Generates a command based on the given parameters.
 *
 * @param i The value of parameter i.
 * @param data Pointer to the data array.
 * @param length The length of the data array.
 * @param key Pointer to the key array.
 * @param forward The value of parameter forward.
 * @param use_default_adapter The value of parameter use_default_adapter.
 * @param i2 The value of parameter i2.
 * @param rfPayload Reference to the pointer for the generated command payload.
 * @return The generated command.
 */
uint8_t do_generate_command(int i, const uint8_t* data, uint8_t length, const uint8_t* key, int forward, int use_default_adapter, int i2, uint8_t*& rfPayload)
{
  if (i2 < 0) 
    i2 = 0;
  uint8_t* payload = 0;
  uint8_t* rfPayloadTmp = 0;

  uint8_t payloadLength = get_payload_with_inner_retry(i, data, length, i2, key, forward, payload);

  uint8_t rfPayloadLength = get_rf_payload(DEFAULT_BLE_FASTCON_ADDRESS, payload, payloadLength, rfPayloadTmp);
  free(payload);


  uint8_t ctx[7];
  whiteningInit(0x25, &ctx[0]);
  uint8_t* result = (uint8_t*)malloc(rfPayloadLength);

  whiteningEncode(rfPayloadTmp, rfPayloadLength, ctx, result);
  rfPayload = (uint8_t*)malloc(rfPayloadLength-15);
  memcpy(rfPayload, result + 15, rfPayloadLength - 15);
  free(result);
  free(rfPayloadTmp);
  return rfPayloadLength-15;
}


void send_scancommand()
{
  uint8_t ble_adv_data[] = { 0x02, 0x01, 0x1A, 0x1B, 0xFF, 0xF0, 0xFF };
  uint8_t* rfPayload = 0;

   uint8_t result[12] =  {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};
  uint8_t rfPayloadLength = do_generate_command(0, 
    result,
    12, nullptr, false , true , 0, rfPayload);

    uint8_t* advPacket = (uint8_t*)malloc(rfPayloadLength + sizeof(ble_adv_data));
    memcpy(advPacket, ble_adv_data, sizeof(ble_adv_data));
    memcpy(advPacket+ sizeof(ble_adv_data), rfPayload, rfPayloadLength);
    free(rfPayload);

    for (int i=0; i<redundancy; i++) {
      send(advPacket, rfPayloadLength + sizeof(ble_adv_data));
      delay(50);
    }
  
  free(advPacket);
}



/**
 * @brief Performs a single control operation.
 *
 * This function takes two parameters, `key` and `result`, which are pointers to uint8_t arrays.
 * It performs a single control operation using the provided key and stores the result in the `result` array.
 *
 * @param key Pointer to the key array.
 * @param result Pointer to the result array.
 */
void single_control(const uint8_t* key, const uint8_t* result)
{
  uint8_t ble_adv_data[] = { 0x02, 0x01, 0x1A, 0x1B, 0xFF, 0xF0, 0xFF };
  uint8_t* rfPayload = 0;
  uint8_t rfPayloadLength = do_generate_command(5, result, 6, key, true /* forward ?*/, true /* use_default_adapter*/, 0, rfPayload);

  uint8_t* advPacket = (uint8_t*)malloc(rfPayloadLength + sizeof(ble_adv_data));
  memcpy(advPacket, ble_adv_data, sizeof(ble_adv_data));
  memcpy(advPacket+ sizeof(ble_adv_data), rfPayload, rfPayloadLength);
  free(rfPayload);

  for (int i=0; i<redundancy; i++) {
    send(advPacket, rfPayloadLength + sizeof(ble_adv_data));
    delay(50);
  }
  
  free(advPacket);
}

/**
 * Sends the specified data over the communication channel.
 *
 * @param data Pointer to the data to be sent.
 * @param dataLength Length of the data to be sent.
 */
void send(uint8_t* data, uint8_t dataLength)
{

  BLEBeacon oBeacon = BLEBeacon();
  oBeacon.setManufacturerId(0xf0ff); // fake Apple 0x004C LSB (ENDIAN_CHANGE_U16!)
  oBeacon.setProximityUUID(BLEUUID(BEACON_UUID));
  oBeacon.setMajor(0);
  oBeacon.setMinor(0);
  BLEAdvertisementData oAdvertisementData = BLEAdvertisementData();
  BLEAdvertisementData oScanResponseData = BLEAdvertisementData();
  
  String strServiceData = "";
  strServiceData += (char)(dataLength-4);     // Len  
  for (int i=4;i<dataLength;i++)
  {
    strServiceData += (char)data[i];
  }
  oAdvertisementData.addData(strServiceData);

  //pAdvertising->setsetAdvertisingParams(0, &adv_params);
  pAdvertising->setAdvertisementData(oAdvertisementData);
  pAdvertising->setScanResponseData(oScanResponseData);  
  pAdvertising->start();
  delay(50);
  pAdvertising->stop();
}
