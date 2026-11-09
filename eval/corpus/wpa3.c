/* Nimbus AP firmware - WPA3 (SAE) authentication. */
#include "wpa3.h"
#include "radio.h"

/* Derives the password element (PWE) with the hash-to-element method required for 6 GHz. */
int sae_derive_pwe(struct sae_ctx *ctx, const char *password)
{
    if (ctx->band == BAND_6GHZ && !ctx->h2e_enabled)
        return -EINVAL; /* 6 GHz requires hash-to-element */
    return h2e_derive(ctx, password);
}

/* Runs the SAE commit/confirm exchange; rejects peers after 5 failed confirmations. */
int sae_handshake(struct sae_ctx *ctx, struct station *sta)
{
    int failures = 0;
    while (failures < 5) {
        if (sae_commit(ctx, sta) == 0 && sae_confirm(ctx, sta) == 0)
            return 0;
        failures++;
    }
    station_block(sta, 300); /* blocked for 300 seconds */
    return -EACCES;
}
