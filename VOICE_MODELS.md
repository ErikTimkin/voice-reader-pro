# Voice pack sources

This branch keeps the release branch untouched and provides seven selectable local voices.

## Voices

| UI name | Engine / speaker | Purpose |
|---|---|---|
| Обычный мужской | Silero v5.6 / `aidar` | Neutral male Russian |
| Обычный женский | Silero v5.6 / `baya` | Neutral female Russian |
| Милый голос | Silero v5.6 / `xenia` | Softer, higher female timbre |
| Желейный медведь | Silero v5.6 / `aidar` + FFmpeg | Lower cartoon-style timbre |
| Армянский 2.0 | Silero v5 CIS / `ru_safarhuja` | Experimental eastern-accent Russian voice |
| Кавказский акцент | Silero v5 CIS / `ru_eduard` | Experimental regional-accent Russian voice |
| Татарский оттенок | Silero v5 CIS / `ru_marat` | Experimental regional-accent Russian voice |

The three eastern voices are different Silero CIS speaker IDs. Their UI descriptions are informal listening labels, not claims of authentic ethnic speech.

## Long-running behavior

- Windows receives a periodic system-awake request while the desktop app is running. The display may still turn off.
- The desktop supervisor restarts the local service after an unexpected failure.
- Discord reconnects are retried with a fresh client after an unrecoverable gateway-client shutdown.
- The public Cloudflare quick tunnel is restarted if its process exits.
- Closing the desktop app or manually pressing Stop shuts the service down.

Windows sleep caused by closing a laptop lid, a manual sleep/shutdown, a reboot/update, power loss, or an internet outage can still interrupt a week-long session. Keep the computer powered and the app window open.

## Notes

A successful Windows package build verifies the local voice engines and desktop startup path; a real multi-day Discord session still needs to be observed on the target computer.
