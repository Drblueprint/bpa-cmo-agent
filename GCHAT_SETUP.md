# Google Chat Read Access — One-Time Setup

**Your part: ~8 minutes in Google Cloud Console.**
**My part: everything else.**

Chrome MCP extension isn't connected on this machine, so I can't drive the browser for you. Follow these steps and I'll take over as soon as the credential file lands.

---

## Step 1. Open Google Cloud Console

Go to **[console.cloud.google.com](https://console.cloud.google.com)**

Sign in with the Google account that is a member of the CMO Agent chat space (the one Kurt/Toby added).

## Step 2. Create a new project

1. Top bar → click the project dropdown (left of the search bar)
2. Click **New Project** (top-right of the dialog)
3. Name: **BPA CMO Agent**
4. Leave organization / location as-is
5. Click **Create**
6. Wait ~10 seconds, then click the project dropdown again and select **BPA CMO Agent**

## Step 3. Enable the Google Chat API

1. Left nav → **APIs & Services** → **Library**
2. Search: **Google Chat API**
3. Click the result → click **Enable**

## Step 4. Configure OAuth consent screen

1. Left nav → **APIs & Services** → **OAuth consent screen**
2. User type: **External** → **Create**
3. Fill in:
   - App name: **BPA CMO Agent**
   - User support email: your email
   - Developer contact: your email
4. **Save and Continue** through scopes (leave empty) and test users pages
5. On Test Users page: **+ Add Users** → add your own Gmail/Workspace address → **Save and Continue**
6. Back to dashboard

## Step 5. Create OAuth credentials

1. Left nav → **APIs & Services** → **Credentials**
2. Top → **+ Create Credentials** → **OAuth client ID**
3. Application type: **Desktop app**
4. Name: **BPA CMO Agent Desktop**
5. Click **Create**
6. In the confirmation dialog → click **Download JSON**

## Step 6. Drop the file where I can find it

Move the downloaded file to:

```
/Users/aarongumm/Desktop/bpa-cmo-agent/gchat_oauth.json
```

(Rename it from the long `client_secret_*.json` Google gives you.)

---

## Then tell me "go"

Once the file is in place, I'll:

1. Run `gchat_auth.py` — browser opens, you click **Allow** once, refresh token saved
2. Run `gchat_poller.py --list-spaces` — confirm the CMO space is visible
3. Do a look-back poll for the last 24h to sanity-check
4. Wire it up so new messages surface into our session

You won't need to touch the console again after this.
