# Deye Web UI

Simple web UI for reading Deye inverter data through Solarman and adjusting an ElectroS EV charger based on available power.

The app includes:

- live inverter and charger state
- start and stop automation
- run one cycle now
- refresh state without sending charger commands
- stop charging now
- scheduler
- settings editor
- live logs viewer
- Docker support

## 1. Request Solarman API Access

You do not generate `appId` and `appSecret` from your email and password yourself.

Your Solarman email and password identify your account. The API credentials are issued by Solarman after OpenAPI activation.

### What you need first

Create and verify a normal Solarman account:

- Solarman Smart
- or Solarman Business

Official registration/login guide:

- https://helpcenter.solarmanpv.com/portal/en/kb/articles/registration-login-solarman-smart-app

### Who to email

Send the request to:

```text
customerservice@solarmanpv.com
```

### What to include

Include:

- your Solarman account email
- your account type: Solarman Smart or Solarman Business
- your role: individual, installer, investor, or distributor
- why you need API access
- whether you want Free Plan or Paid Plan
- your website or app URL if applicable
- this agreement sentence:

```text
I have read and understood all terms of the Developer Agreement and agree to be bound by them.
```

### Example email

```text
Subject: Request for SOLARMAN OpenAPI activation

Hello SOLARMAN team,

I would like to request activation of SOLARMAN OpenAPI for my account.

My SOLARMAN account email: your_email@example.com
Account type: SOLARMAN Smart
Role: individual
Requested plan: Free Plan

Reason for API access:
I want to read inverter and plant data from my Deye inverter through the SOLARMAN OpenAPI for personal monitoring and home automation.

Website or application URL:
No public website, personal/internal use only.

I have read and understood all terms of the Developer Agreement and agree to be bound by them.

Best regards,
Your name
```

### What Solarman sends back

After approval, Solarman should provide:

- `APP ID`
- `APP SECRET`

Your normal Solarman login is still used too:

- email
- password

Important auth details used by this project:

- token endpoint base URL: `https://globalapi.solarmanpv.com`
- `appId` goes in the URL query
- `email`, `appSecret`, and lowercase SHA-256 `password` go in the request body

## 2. Prepare Local Config

This project uses a local `.env` file in the repository root.

Create it from the example:

```bash
cp .env.example .env
```

Then edit `.env` and fill in your real values.

### Required Solarman values

```text
SOLARMAN_APP_ID=your_app_id
SOLARMAN_APP_SECRET=your_app_secret
SOLARMAN_PASSWORD=your_solarman_password
SOLARMAN_EMAIL=your_email@example.com
SOLARMAN_BASE_URL=https://globalapi.solarmanpv.com
SOLARMAN_STATION_ID=your_station_id
```

### Required charger values

```text
CHARGER_LOGIN=your_charger_login
CHARGER_PASSWORD=your_charger_password
```

### Useful app settings

```text
CHARGER_PHASES=1
CHARGER_VOLTAGE=230
CHARGER_MIN_AMPS=6
CHARGER_MAX_AMPS=14
CHARGER_RESERVE_WATTS=250
UPDATE_INTERVAL_SECONDS=360
APP_TIMEZONE=Europe/Kyiv
```

## 3. Find `SOLARMAN_STATION_ID`

If you already know your station ID, put it in `.env`.

If `SOLARMAN_STATION_ID` is not set, the app will try to fetch the first available station automatically through the Solarman API.

So `SOLARMAN_STATION_ID` is optional.

It is still recommended to set it explicitly if:

- your account has more than one station
- you want to be sure the app always uses the same plant

## 4. Run with Docker

Start the app:

```bash
docker compose up --build
```

Then open:

```text
http://localhost:8080
```

## 5. How the App Works

### Run Job

- `Start Automation` starts the background worker
- `Stop Automation` disables automatic cycles
- `Run Now` runs one full automation cycle immediately
- `Refresh State` reads inverter and charger state without sending charger commands
- `Stop Charging Now` sends a manual charger stop command

### Scheduler

You can configure:

- scheduler enabled
- active start time
- active stop time
- update interval

### Configuration

You can configure:

- min amps
- max amps
- charger voltage
- charger phases
- reserve watts

## 6. Runtime Files

Runtime files are stored in:

- `data/settings.json`
- `data/app.log`

These are mounted into the container through Docker Compose:

```yaml
volumes:
  - ./data:/app/data
```

That means the files stay on your host machine and survive container restarts.

## 7. Safe Sharing

This repository is ready to share on GitHub:

- real secrets stay in `.env`
- `.env.example` is safe to commit
- `.env` is ignored by Git
- `data/app.log` is ignored by Git
- `data/settings.json` is ignored by Git

## Notes

- The web app starts idle. Automation does not begin on container startup.
- The worker starts only after `Start Automation` or `Run Now`.
