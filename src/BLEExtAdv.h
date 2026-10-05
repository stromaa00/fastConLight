#ifndef BLEEXTADV
#define BLEEXTADV

#include <Arduino.h>
#include <esp_gap_ble_api.h>



class BLEExtAdv
{
private:
    u_int8_t m_manufacturer[2] = {0, 0};
    bool m_hasManufacturData = false;
    int m_iManufacturerData_len; 
    u_int8_t m_cManufacturerData[30];
    esp_ble_gap_ext_adv_report_t m_advertisedDevice;

public:
    BLEExtAdv(esp_ble_gap_ext_adv_report_t advertisedDevice);
    bool haveManufacturerData() { return m_hasManufacturData; };
    //esp_bd_addr_t& getAddress();
};

/*
 * BLEAdvertisedDevice.h
 *
 *  Created on: Jul 3, 2017
 *      Author: kolban
 */

#include "sdkconfig.h"
#include <esp_gattc_api.h>

#include <map>
#include <vector>

#include "BLEAddress.h"
#include "BLEScan.h"
#include "BLEUUID.h"

class BLEExtAdvertisedDevice : public BLEAdvertisedDevice {
public:
	BLEExtAdvertisedDevice();
    void parseAdvertisement(uint8_t* payload, size_t total_len=62);

	void fromReportedDevice(esp_ble_gap_ext_adv_report_t reportedDevice)
	{
		this->setAddress(BLEAddress(reportedDevice.addr));
		this->setAddressType((esp_ble_addr_type_t) reportedDevice.addr_type);
		this->setTXPower(reportedDevice.rssi);
		this->parseAdvertisement(reportedDevice.adv_data, reportedDevice.adv_data_len);
	}

	BLEAddress  getAddress();
	uint16_t    getAppearance();
	String getManufacturerData();
	String getName();
	int         getRSSI();
	BLEScan*    getScan();
	String getServiceData();
	String getServiceData(int i);
	BLEUUID     getServiceDataUUID();
	BLEUUID     getServiceDataUUID(int i);
	BLEUUID     getServiceUUID();
	BLEUUID     getServiceUUID(int i);
	int         getServiceDataCount();
	int         getServiceDataUUIDCount();
	int         getServiceUUIDCount();
	int8_t      getTXPower();
	uint8_t* 	getPayload();
	size_t		getPayloadLength();
	esp_ble_addr_type_t getAddressType();
	void setAddressType(esp_ble_addr_type_t type);


	bool		isAdvertisingService(BLEUUID uuid);
	bool        haveAppearance();
	bool        haveManufacturerData();
	bool        haveName();
	bool        haveRSSI();
	bool        haveServiceData();
	bool        haveServiceUUID();
	bool        haveTXPower();

	String toString();

private:
	void setPayload(uint8_t* payload, size_t total_len=62);
	void setAddress(BLEAddress address);
	void setAdFlag(uint8_t adFlag);
	void setAdvertizementResult(uint8_t* payload);
	void setAppearance(uint16_t appearance);
	void setManufacturerData(String manufacturerData);
	void setName(String name);
	void setRSSI(int rssi);
	void setScan(BLEScan* pScan);
	void setServiceData(String data);
	void setServiceDataUUID(BLEUUID uuid);
	void setServiceUUID(const char* serviceUUID);
	void setServiceUUID(BLEUUID serviceUUID);
	void setTXPower(int8_t txPower);

	bool m_haveAppearance;
	bool m_haveManufacturerData;
	bool m_haveName;
	bool m_haveRSSI;
	bool m_haveTXPower;


	BLEAddress  m_address = BLEAddress((uint8_t*)"\0\0\0\0\0\0");
	uint8_t     m_adFlag;
	uint16_t    m_appearance;
	int         m_deviceType;
	String m_manufacturerData;
	String m_name;
	BLEScan*    m_pScan;
	int         m_rssi;
	std::vector<BLEUUID> m_serviceUUIDs;
	int8_t      m_txPower;
	std::vector<String> m_serviceData;
	std::vector<BLEUUID> m_serviceDataUUIDs;
	uint8_t*	m_payload;
	size_t		m_payloadLength = 0;
	esp_ble_addr_type_t m_addressType;
};



#endif