# Vendored Audi client — one-time copy step

This folder holds the myAudi API client copied from the actively maintained Home Assistant
integration **[audiconnect/audi_connect_ha](https://github.com/audiconnect/audi_connect_ha)**.
We vendor it because the previous standalone PyPI library (`audiconnectpy`) was deleted by its
author. The client uses the same myAudi login you already configured in `.env`.

The `.py` client files are **not committed** to this repo — copy them from the source once:

## Copy the files (PowerShell, from the project root)

```powershell
# 1. Get the source next to your project
git clone https://github.com/audiconnect/audi_connect_ha.git ..\audi_connect_ha

# 2. Copy the six client modules into this folder
$src = "..\audi_connect_ha\custom_components\audiconnect"
foreach ($f in "audi_connect_account.py","audi_services.py","audi_api.py","audi_models.py","util.py","const.py") {
    Copy-Item "$src\$f" "ev_charge\vendor\audiconnect\$f"
}
```

(macOS/Linux: same six files, `cp ../audi_connect_ha/custom_components/audiconnect/{audi_connect_account,audi_services,audi_api,audi_models,util,const}.py ev_charge/vendor/audiconnect/`.)

After copying, this folder should contain:

```
__init__.py   (already here)
README.md     (already here)
audi_connect_account.py
audi_services.py
audi_api.py
audi_models.py
util.py
const.py
```

## Verify

```powershell
.\.venv\Scripts\python.exe check_battery.py --dump
```

If the run complains that another `audiconnect` module is missing (an import we didn't anticipate),
copy that one file too from the same source folder and re-run.

## License / attribution

These files are the property of the `audi_connect_ha` authors and retain their original license
(see the source repository). They are included here unmodified for personal use. Do not relicense
them; if you redistribute this project, keep this attribution and the upstream license.
