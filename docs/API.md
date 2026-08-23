# The GovDeals / AllSurplus JSON API

`www.govdeals.com` is an Angular SPA behind Akamai Bot Manager: a plain fetch
returns an empty shell, and non-browser clients get HTTP 403. The API host
behind it, `maestro.lqdt1.com`, is **not** bot-protected, so plain HTTP works.

Constants come from `main.js` on the public site:

```
maestroUrl    https://maestro.lqdt1.com
maestroApiKey af93060f-337e-428c-87b8-c74b5837d6cd   # public client key
fileServerUrl https://files.lqdt1.com
```

## Required headers

```
x-api-key: af93060f-337e-428c-87b8-c74b5837d6cd
x-user-id: -1
x-api-correlation-id: <any uuid>
User-Agent: <any browser UA>
Content-Type: application/json
```

Three of these are easy to get wrong:

- **`x-user-id` must be `-1`**, not `0`. `0` returns `{"x-user-id":["User ID is invalid."]}`.
  The bundle does `.set("x-user-id", N ?? "-1")`.
- **`x-api-correlation-id` is mandatory.** Omitting it returns HTTP 400.
- **A browser `User-Agent` is required.** Python's default `urllib` UA gets 403.

## `POST /search/list`

```jsonc
{
  "categoryIds": "", "businessId": "GD", "searchText": "optiplex",
  "isQAL": false, "page": 1, "displayRows": 100,
  "sortField": "bestfit", "sortOrder": "desc",
  "requestType": "search", "responseStyle": "fullResponse",
  "facets": [], "facetsFilter": [],
  "timeType": "",            // "MicrositeSoldAssets" for SOLD lots
  "sellerTypeId": null,
  "accountIds": []           // [7484] to scope to one seller; [] = all sellers
}
```

Total result count comes back in the **`x-total-count` response header**, not
the body.

### Sold lots

Set `timeType` to `"MicrositeSoldAssets"`. There is also an `isSoldAssets`
boolean that looks like the right field and is **silently ignored** — it
returns live lots with `isSoldAuction: false`. Sold records carry
`isSoldAuction: true` and `currentBid` = the realized hammer price.

Sold search works with `accountIds: []`, giving the archive across all sellers
(~6,300 records for "optiplex" alone).

## `POST /assets/{assetId}/{accountId}/false`

Body: `{"businessId": "GD", "siteId": 0}`

Note the param order — **assetId first**. Reversed, it returns HTTP 204 with an
empty body rather than an error. The trailing segment is `isPreviewAsset`; it
must be `false`, not `0`.

Returns the full lot detail including `assetLongDesc`, `assetPhotos`,
`assetAttributes`, and `assetAttachments`.

## Attachments

```
https://files.lqdt1.com/photos/{accountId}/Attachments/{urlencoded fileName}
```

Photos use `https://files.lqdt1.com{assetPhotos[i]}`.

## eBay

There is deliberately no eBay scraper in this project. eBay serves a
human-verification challenge to non-browser clients *and* to automated
browsers. The supported path is the official API with your own credentials —
see `EbayAdapter` in `src/pcpartscan/pricing.py`. Without credentials the
adapter is inert and the grader drops that source from the blend.
