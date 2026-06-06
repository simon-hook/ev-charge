# ev-charge — Audi Q4 nightly battery monitor

A small Python tool that logs in to your **myAudi** account once a night, reads the **Audi Q4
e-tron** battery level, and sends a **push notification to your phone** when it drops **below 40%**
— so you remember to plug in.

- **Car data:** [`audiconnectpy`](https://github.com/cyr-ius/audiconnectpy) (unofficial myAudi
  client; the same library behind the Home Assistant Audi integration).
- **Schedule:** a cron job on your own always-on machine.
- **Alerts:** [ntfy](https://ntfy.sh) by default (free, no account); Pushover or Telegram optional.

> ⚠️ `audiconnectpy` is unofficial and reverse-engineered. Audi can change their cloud at any time
> and break it. The version is pinned in `requirements.txt`, and the battery lookup fails *loudly*
> rather than reporting a wrong number.

## How the push reaches your phone

Your script makes one outbound HTTPS request to a push provider; the provider's app on your phone
shows the notification. With the default (ntfy): install the **ntfy** app, subscribe to a private
topic name you choose, and the script `POST`s your alert to `https://ntfy.sh/<your-topic>`. No
server of your own and no inbound connection to your phone.

## Setup

Install happens in **two steps** — the core deps (which always succeed), then the Audi client
(which can be finicky and is kept separate so it can't block the rest):

```bash
git clone <this-repo> ev-charge && cd ev-charge
python3 -m venv .venv

# 1. Core dependencies — always installs cleanly:
.venv/bin/pip install -r requirements.txt

# 2. Audi cloud client — needed for real battery reads (not for --test-notify):
.venv/bin/pip install -r requirements-audi.txt

cp .env.example .env
# edit .env with your myAudi login + ntfy topic (see below)
```

> Keeping `audiconnectpy` in its own file matters: if it's listed alongside the core deps and
> fails to resolve, pip aborts the **entire** install and you end up with nothing (e.g.
> `ModuleNotFoundError: No module named 'requests'`).

### If `audiconnectpy` (step 2) won't install

`pip` may report `Could not find a version that satisfies the requirement audiconnectpy
(from versions: none)`. The core tool and `--test-notify` still work without it; only the live
battery read needs it. Fixes, in order of preference:

1. **Use Python 3.12.** `audiconnectpy` does not support **Python 3.13+**, and
   `(from versions: none)` is exactly what you see when your Python is too new. Check with
   `python --version`. On Windows, install 3.12 and rebuild the venv with it (leaves 3.13 intact):
   ```powershell
   winget install Python.Python.3.12
   Remove-Item -Recurse -Force .venv      # drop the old venv
   py -3.12 -m venv .venv                  # build a 3.12 venv
   .\.venv\Scripts\pip.exe install -r requirements.txt
   .\.venv\Scripts\pip.exe install -r requirements-audi.txt
   ```
2. **Install from source** (needs [Git](https://git-scm.com/) on PATH):
   ```bash
   pip install "git+https://github.com/cyr-ius/audiconnectpy.git"
   ```

### Configure `.env`

| Variable | Required | Notes |
|---|---|---|
| `AUDI_USERNAME` / `AUDI_PASSWORD` | yes | Your myAudi app login. |
| `AUDI_COUNTRY` | yes | Two-letter code for your account, e.g. `GB`, `DE`, `US`. |
| `AUDI_SPIN` | no | S-PIN; not needed for read-only battery checks. |
| `AUDI_VIN` | no | Pin to one car. Optional if you only have one. |
| `BATTERY_THRESHOLD` | no | Default `40`. Alert fires when level is **strictly below** this. |
| `NOTIFY_BACKEND` | no | `ntfy` (default), `pushover`, or `telegram`. |
| `NOTIFY_ON_ERROR` | no | `true` to also get pushed when the check itself fails. Default `false`. |
| `NTFY_TOPIC` / `NTFY_SERVER` | ntfy | Topic is a password — pick something unguessable. |
| `PUSHOVER_TOKEN` / `PUSHOVER_USER` | pushover | From your Pushover account + app registration. |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | telegram | From @BotFather + your chat id. |

## Verify it works

Run these from the project directory (so `.env` is picked up):

```bash
# 1. Notifications: send a test push to your phone (does not contact the car).
.venv/bin/python check_battery.py --test-notify

# 2. Live read: confirm the car is found and the battery field is detected.
.venv/bin/python check_battery.py --dump

# 3. End-to-end: send the low-battery alert regardless of the real level.
.venv/bin/python check_battery.py --force

# 4. Normal run: read battery, alert only if below the threshold.
.venv/bin/python check_battery.py
```

If `--dump` shows your battery but the headline `battery=…%` looks wrong, open an issue with the
(redacted) dump — the detector may need another candidate field for your model/version.

## Schedule it nightly

### macOS / Linux

See `crontab.example`. In short, `crontab -e` and add (adjust the paths):

```cron
0 2 * * * cd /path/to/ev-charge && /path/to/ev-charge/.venv/bin/python check_battery.py >> /path/to/ev-charge/battery.log 2>&1
```

`cd`-ing into the project dir lets `python-dotenv` load `./.env`. Watch it with
`tail -f battery.log`.

### Windows (Task Scheduler)

Use the bundled `check_battery.bat` (it `cd`s to the repo and logs to `battery.log`). Create the
task from PowerShell — the flags make it run after a missed start (e.g. the laptop was asleep) and
wake the machine if it can:

```powershell
$action  = New-ScheduledTaskAction -Execute "C:\path\to\ev-charge\check_battery.bat"
$trigger = New-ScheduledTaskTrigger -Daily -At 2am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun
Register-ScheduledTask -TaskName "Audi Q4 battery check" -Action $action -Trigger $trigger -Settings $settings
```

- `-StartWhenAvailable` runs the job as soon as possible if the scheduled time was missed.
- `-WakeToRun` wakes the laptop from **sleep** (not shutdown, and only if hardware/power settings allow).
- A laptop that's fully **shut down** at 2am won't run the job at all — pick a time the machine is on,
  or use an always-on host.

> **Note:** the laptop must be awake (or able to wake) at the scheduled time. If it's usually closed
> and powered off overnight, schedule a daytime time instead, or run this on a Raspberry Pi /
> GitHub Actions instead.

## Tests

```bash
.venv/bin/python -m pytest
```

The tests mock the car and the network, so they need no credentials and make no real requests.
They cover the threshold logic, each notification backend, and the battery-field detector.
