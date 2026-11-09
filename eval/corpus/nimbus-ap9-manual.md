# Nimbus AP-9 Access Point — User Manual

## Installation

Mount the Nimbus AP-9 on a ceiling or wall at least 2.5 metres above the floor. Power it with an 802.3bt PoE
injector (60 W); the older 802.3at injectors are not supported because the radios need more than 30 W.
The status LED is white while booting and turns solid blue when the access point is ready.

## Radios

The AP-9 has three radios: 2.4 GHz (2x2), 5 GHz (4x4) and 6 GHz (4x4). The 6 GHz radio only works with
WPA3 security. Channel width defaults to 20 MHz on 2.4 GHz, 80 MHz on 5 GHz and 160 MHz on 6 GHz.

## Security

WPA3-Personal is enabled from Settings > Wireless > Security. WPA2 networks can still be created for older
clients, but they are not available on the 6 GHz radio. The management interface uses HTTPS on port 8443.

## Factory reset

Hold the recessed reset button for 15 seconds until the status LED blinks amber three times. The default
administrator password is printed on the label on the back of the device, next to the serial number.

## Firmware

Firmware updates are installed from Settings > Maintenance > Firmware. Version 7.2 added band steering;
version 7.4 added the roaming assistant, which moves clients when their signal drops below -72 dBm.
