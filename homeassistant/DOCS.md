# Pryces Portfolio

Self-hosted, multi-broker portfolio tracker: positions, realized and unrealized P&L,
dividends, and money-weighted (XIRR) / time-weighted (TWR) returns — with the CaudalNet
dashboard served straight into the Home Assistant sidebar.

## Installation

The app is not published to a registry; it is built locally from the `/addons` folder.

1. Build the bundle on your workstation:

   ```bash
   cd caudalnet-web && npm run build
   cd ../pryces-api && make ha-app
   ```

2. Copy `pryces-api/build/ha-app/` to `/addons/pryces/` on the Home Assistant host
   (the **Samba share** or **Advanced SSH & Web Terminal** app both expose that folder).
3. In Home Assistant, go to **Settings → Apps → App store**, open the ⋮ menu and click
   **Check for updates**. *Pryces Portfolio* appears under **Local apps**.
4. Install it. The first build takes a few minutes.
5. Start it, and enable **Show in sidebar**.

## Configuration

| Option | Default | Purpose |
| --- | --- | --- |
| `max_fetch_workers` | `2` | Parallel quote lookups. Keep low — Yahoo rate-limits. |
| `cache_ttl_seconds` | `300` | How long live quotes are cached. |
| `cache_closed_ttl_seconds` | `3600` | Quote cache while the exchange is closed. |
| `cache_fx_ttl_seconds` | `3600` | FX rate cache. |
| `log_level` | `info` | Set to `debug` when diagnosing a problem. |
| `telegram_bot_token` | — | Optional; only for the Telegram notification scripts. |
| `telegram_group_id` | — | Optional; as above. |

## Data and backups

Portfolios live in `/data/pryces` on the app's persistent volume. That survives restarts
and updates, and is included in Home Assistant's own backups.

You can still export a portable copy from the dashboard's backup/restore screen, which
writes the same versioned JSON document the CLI produces.

## Exposing the figures to Home Assistant

Ingress gives you the dashboard, but not entities. To get sensors you can graph and
automate on, add a `rest` block to `configuration.yaml`. Because ingress does not expose
a port, point it at the app over the internal Docker network:

```yaml
rest:
  - resource: http://a0d7b954-pryces:8000/api/overview
    scan_interval: 300
    sensor:
      - name: "Portfolio Total Value"
        value_template: "{{ value_json.portfolio.total_value | float }}"
        unit_of_measurement: "EUR"
        device_class: monetary
        state_class: total
      - name: "Portfolio Total Profit"
        value_template: "{{ value_json.portfolio.total_profit | float }}"
        unit_of_measurement: "EUR"
        device_class: monetary
        state_class: total
      - name: "Portfolio Return"
        value_template: "{{ value_json.portfolio.total_return_pct | float }}"
        unit_of_measurement: "%"
        state_class: measurement
```

The hostname is shown on the app's **Info** tab. Every monetary field is serialized as a
string to preserve decimal precision, hence the `| float` casts.

Do not poll faster than a few minutes: `/api/overview` performs live price and FX lookups.

## Notes

- There is no authentication in the API itself. Ingress is what protects it — the app is
  never exposed on your network, and Home Assistant's own login guards the sidebar entry.
- The dashboard uses hash-based routing so deep links survive the ingress path prefix.
