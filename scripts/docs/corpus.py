"""Demo content for the user-guide screenshots, in English and Italian (a coherent set per UI language)."""

from __future__ import annotations

RADIO_C = """/* AirLink X200 radio driver */
#include "radio.h"

#define MAX_POWER_DBM 20

static int current_channel = 0;

int radio_set_power(int dbm)
{
    if (dbm < 1 || dbm > MAX_POWER_DBM)
        return -1;
    return hw_write(REG_TXPOWER, dbm);
}

int radio_set_channel(int channel)
{
    if (channel < 0 || channel > 165)
        return -1;
    current_channel = channel;
    return hw_write(REG_CHANNEL, channel);
}

int radio_scan(void)
{
    int best = radio_least_busy();
    return radio_set_channel(best);
}
"""

CORPUS = {
    "en": {
        "locale": "en",
        "project": "AirLink X200",
        "workspace": "Product documentation",
        "notebooks": ["User manual", "Firmware"],
        "manual_pdf": [
            [
                (22, "AirLink X200 User Manual"),
                (15, "1. Getting started"),
                (11, "The AirLink X200 is a dual band wireless access point for offices."),
                (11, "Connect the power adapter and the network cable, then wait for the power LED."),
                (11, "The power LED is solid green when the access point is ready for use."),
                (15, "2. Factory reset"),
                (11, "To restore the factory settings, hold the reset button for ten seconds"),
                (11, "until the power LED blinks amber. All settings are erased and the default"),
                (11, "administrator password printed on the label under the device is valid again."),
            ],
            [
                (15, "3. Wireless settings"),
                (11, "Open the web console and choose Wireless, then Radio."),
                (11, "The channel can be set manually or left on auto: the access point then picks"),
                (11, "the least busy channel at every start. The transmit power ranges from 1 to 20"),
                (11, "dBm and is 17 dBm by default. Lower it in dense deployments to reduce interference."),
                (15, "4. Firmware update"),
                (11, "Open System, then Firmware, and upload the .bin file. Do not power off the"),
                (11, "device: the update takes about three minutes and the access point restarts."),
            ],
        ],
        "manual_name": "airlink-x200-manual.pdf",
        "quickstart_name": "quick-start.md",
        "quickstart": (
            "# Quick start\n\n## Mounting\n\nFix the bracket to the ceiling with the two supplied screws, then "
            "clip the AirLink X200 onto the bracket until it clicks.\n\n## Powering\n\nThe device is powered "
            "over Ethernet (PoE, 802.3af). Connect it to a PoE switch port and wait about one minute for "
            "the power LED to turn solid green.\n\n## First login\n\nOpen the address printed on the label "
            "and sign in as administrator. You are asked to change the default password at the first "
            "login.\n"
        ),
        "zip_name": "firmware-4.2-src.zip",
        "notes_title": "Open questions for the next release",
        "note": "Check whether the transmit power limit is 20 dBm in every country (see manual, section 3).",
        "questions": [
            "How do I restore the factory settings?",
            "What is the default transmit power?",
            "How do I update the firmware?",
        ],
        "summary": "User manual of the AirLink X200 access point: first start, factory reset, wireless "
        "settings and firmware update.",
        "summary_questions": [
            "How is the factory reset performed?",
            "Which transmit power does the access point use by default?",
            "How long does a firmware update take?",
        ],
        "research": "Compare the factory reset and the firmware update procedures of the AirLink X200",
        "entities": [
            ("AirLink X200", "product", "The dual band wireless access point described by the manual."),
            ("reset button", "component", "Held for ten seconds to restore the factory settings."),
            ("web console", "component", "Where the radio channel and transmit power are configured."),
            ("transmit power", "concept", "Ranges from 1 to 20 dBm, 17 dBm by default."),
            ("firmware", "concept", "Updated from System > Firmware, takes about three minutes."),
            ("radio_set_channel", "function", "Writes the channel register of the radio."),
        ],
        "relations": [
            ("AirLink X200", "reset button", "has", "The access point has a reset button."),
            ("web console", "transmit power", "configures", "The web console sets the transmit power."),
            ("AirLink X200", "firmware", "runs", "The access point runs the firmware."),
        ],
    },
    "it": {
        "locale": "it",
        "project": "AirLink X200",
        "workspace": "Documentazione di prodotto",
        "notebooks": ["Manuale utente", "Firmware"],
        "manual_pdf": [
            [
                (22, "AirLink X200 - Manuale utente"),
                (15, "1. Primo avvio"),
                (11, "AirLink X200 è un access point wireless dual band per uffici."),
                (11, "Collega l'alimentatore e il cavo di rete, poi attendi il LED di alimentazione."),
                (11, "Il LED di alimentazione è verde fisso quando l'access point è pronto all'uso."),
                (15, "2. Ripristino di fabbrica"),
                (11, "Per ripristinare le impostazioni di fabbrica tieni premuto il pulsante di reset"),
                (11, "per dieci secondi, finché il LED di alimentazione lampeggia in giallo. Tutte le"),
                (11, "impostazioni vengono cancellate e vale di nuovo la password di amministratore"),
                (11, "predefinita stampata sull'etichetta sotto il dispositivo."),
            ],
            [
                (15, "3. Impostazioni wireless"),
                (11, "Apri la console web e scegli Wireless, poi Radio."),
                (11, "Il canale si imposta a mano oppure si lascia su automatico: a ogni avvio l'access"),
                (11, "point sceglie il canale meno occupato. La potenza di trasmissione va da 1 a 20"),
                (11, "dBm ed è di 17 dBm per impostazione predefinita. Riducila nelle installazioni dense."),
                (15, "4. Aggiornamento del firmware"),
                (11, "Apri Sistema, poi Firmware, e carica il file .bin. Non spegnere il dispositivo:"),
                (11, "l'aggiornamento dura circa tre minuti e l'access point si riavvia."),
            ],
        ],
        "manual_name": "airlink-x200-manuale.pdf",
        "quickstart_name": "guida-rapida.md",
        "quickstart": (
            "# Guida rapida\n\n## Montaggio\n\nFissa la staffa al soffitto con le due viti in dotazione, poi "
            "aggancia AirLink X200 alla staffa fino allo scatto.\n\n## Alimentazione\n\nIl dispositivo è "
            "alimentato via Ethernet (PoE, 802.3af). Collegalo a una porta PoE dello switch e attendi circa un "
            "minuto che il LED di alimentazione diventi verde fisso.\n\n## Primo accesso\n\nApri l'indirizzo "
            "stampato sull'etichetta ed entra come amministratore. Al primo accesso ti viene chiesto di "
            "cambiare la password predefinita.\n"
        ),
        "zip_name": "firmware-4.2-sorgenti.zip",
        "notes_title": "Domande aperte per la prossima release",
        "note": "Verificare se il limite di potenza di 20 dBm vale in ogni Paese (vedi manuale, sezione 3).",
        "questions": [
            "Come si ripristinano le impostazioni di fabbrica?",
            "Qual è la potenza di trasmissione predefinita?",
            "Come si aggiorna il firmware?",
        ],
        "summary": "Manuale utente dell'access point AirLink X200: primo avvio, ripristino di fabbrica, "
        "impostazioni wireless e aggiornamento del firmware.",
        "summary_questions": [
            "Come si esegue il ripristino di fabbrica?",
            "Quale potenza di trasmissione usa di default l'access point?",
            "Quanto dura un aggiornamento del firmware?",
        ],
        "research": "Confronta le procedure di ripristino di fabbrica e di aggiornamento firmware di AirLink X200",
        "entities": [
            ("AirLink X200", "product", "L'access point wireless dual band descritto dal manuale."),
            ("pulsante di reset", "component", "Tenuto premuto dieci secondi ripristina le impostazioni."),
            ("console web", "component", "Dove si configurano canale radio e potenza di trasmissione."),
            ("potenza di trasmissione", "concept", "Da 1 a 20 dBm, 17 dBm di default."),
            ("firmware", "concept", "Si aggiorna da Sistema > Firmware, dura circa tre minuti."),
            ("radio_set_channel", "function", "Scrive il registro del canale della radio."),
        ],
        "relations": [
            ("AirLink X200", "pulsante di reset", "has", "L'access point ha un pulsante di reset."),
            ("console web", "potenza di trasmissione", "configures", "La console web imposta la potenza."),
            ("AirLink X200", "firmware", "runs", "L'access point esegue il firmware."),
        ],
    },
}
