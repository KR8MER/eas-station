# TTS Troubleshooting Guide

## Why TTS Doesn't Work Despite Having API Keys

### Problem Summary

As of December 17, 2025, TTS configuration was migrated from environment variables to database storage. This means:

1. ❌ Environment variables (`AZURE_OPENAI_CONFIG`, `EAS_TTS_PROVIDER`, etc.) are **no longer used**
2. ❌ Default migration settings have TTS **disabled** (`enabled=false`, `provider=''`)
3. ✅ All TTS configuration must now be done via the **web UI**

---

## Quick Fix Checklist

### ☑️ Step 1: Access Admin UI
Navigate to: `http://your-server/admin/tts`

### ☑️ Step 2: Enable TTS
- Set **TTS Enabled**: `Enabled`
- Set **TTS Provider**: `Azure OpenAI` (or your preferred provider)

### ☑️ Step 3: Configure Azure OpenAI (if using Azure)

#### Required Fields:

**Endpoint URL** - Must be in exact format:
```
https://YOUR-RESOURCE.openai.azure.com/openai/deployments/YOUR-DEPLOYMENT/audio/speech?api-version=2024-03-01-preview
```

**Replace:**
- `YOUR-RESOURCE`: Your Azure OpenAI resource name
- `YOUR-DEPLOYMENT`: Your TTS deployment name (e.g., `tts-1`, `tts-hd`)

**Example:**
```
https://mycompany-ai.openai.azure.com/openai/deployments/tts-hd/audio/speech?api-version=2024-03-01-preview
```

**API Key:**
- Your Azure OpenAI API key (starts with a long alphanumeric string)
- Found in Azure Portal → Your OpenAI Resource → Keys and Endpoint

**Voice** (choose one):
- `alloy` - Neutral, balanced
- `echo` - Male, clear
- `fable` - British, warm
- `onyx` - Deep, authoritative
- `nova` - Female, energetic
- `shimmer` - Female, soft

**Model:**
- `tts-1` - Standard quality, faster
- `tts-1-hd` - High definition, slower

**Speed:**
- Range: `0.25` to `4.0`
- Default: `1.0`

### ☑️ Step 4: Save Settings
Click **Save Settings** button

---

## Common Issues & Solutions

### Issue 1: "Azure OpenAI endpoint is incomplete"

**Error in logs:**
```
Expected full format: https://YOUR_RESOURCE.openai.azure.com/openai/deployments/YOUR_DEPLOYMENT/audio/speech?api-version=...
```

**Solution:**
Your endpoint URL is missing required components. Ensure it includes:
1. `/openai/deployments/YOUR_DEPLOYMENT/` in the path
2. `/audio/speech` at the end
3. `?api-version=...` query parameter

### Issue 2: "Could not extract deployment name from Azure endpoint"

**Error in logs:**
```
The endpoint must include '/deployments/YOUR_DEPLOYMENT/' in the path.
```

**Solution:**
The code extracts the deployment name from the URL to use as the model parameter. Fix your endpoint format.

**Wrong:**
```
https://myresource.openai.azure.com/audio/speech
```

**Correct:**
```
https://myresource.openai.azure.com/openai/deployments/tts-hd/audio/speech?api-version=2024-03-01-preview
```

### Issue 3: API returns 404 Not Found

**Possible causes:**
1. Deployment name in URL doesn't exist in your Azure resource
2. Endpoint URL is incorrect
3. API version is wrong

**Solution:**
1. Log into Azure Portal
2. Navigate to your OpenAI resource
3. Go to "Deployments" section
4. Verify your TTS deployment exists and note its exact name
5. Use that exact name in your endpoint URL

### Issue 4: API returns 401 Unauthorized

**Possible causes:**
1. API key is incorrect
2. API key has been regenerated/expired
3. Wrong resource

**Solution:**
1. Go to Azure Portal → Your OpenAI Resource → Keys and Endpoint
2. Copy the key (Key 1 or Key 2)
3. Paste it exactly in the TTS settings (no extra spaces)
4. Save settings

### Issue 5: TTS still using old environment variables

**This is no longer possible.** As of the December 17 migration:
- Code in `app_utils/eas.py:111-131` only reads from database
- Environment variables are completely ignored
- All configuration must be via web UI at `/admin/tts`

### Issue 6: TTS settings not taking effect (FIXED)

**Problem:**
You configured TTS via the web UI, but the broadcast builder still doesn't use TTS.

**Root Cause (FIXED as of this commit):**
The EAS config was loaded once at app startup and cached. Even after updating TTS settings in the database via `/admin/tts`, the broadcast builder used the stale cached config.

**Solution:**
The code now reloads TTS configuration fresh from the database each time audio is generated. Changes to TTS settings take effect immediately without requiring an app restart.

**Fixed Files:**
- `webapp/eas/workflow.py:232-242` - Workflow builder now reloads config
- `webapp/admin/audio.py:756-764` - Admin audio builder now reloads config

**Verification:**
1. Update TTS settings at `/admin/tts`
2. Generate a test alert immediately
3. TTS should work with the new settings (no restart needed)

---

## Testing TTS Configuration

### Option 1: Test via the Admin UI

Navigate to **Admin → Settings → TTS** and use the **"Test TTS"** button. This sends a short test phrase through the configured provider and reports success or the exact error.

1. Go to `http://your-server/eas/workflow`
2. Create a test alert
3. Check for TTS voiceover in generated audio
4. Check logs for TTS errors

### Option 3: Check Application Logs

Look for TTS-related messages:
```bash
grep -i "tts\|azure openai" logs/eas_station.log
```

Common log messages:
- ✅ `Appended Azure OpenAI TTS voiceover using voice alloy`
- ❌ `Azure OpenAI TTS credentials not configured`
- ❌ `Azure OpenAI TTS API returned status 404`
- ❌ `Azure OpenAI endpoint is incomplete`

---

## Code References

### Where TTS Settings Are Loaded
- **File:** `app_utils/eas.py:111-131`
- **Function:** `load_eas_config()`

### Where TTS API Calls Are Made
- **File:** `app_utils/eas_tts.py:181-353`
- **Class:** `TTSEngine`
- **Method:** `_generate_azure_openai_voiceover()`

### Where Settings Are Stored
- **Database Table:** `tts_settings`
- **Model:** `app_core/models.py:871-910` (`TTSSettings`)
- **Helper:** `app_core/tts_settings.py`

### Admin UI
- **Route:** `/admin/tts` (`webapp/admin/tts.py`)
- **Template:** `templates/admin/tts.html`
- **API Endpoint:** `/admin/api/tts/settings` (PUT)

---

## Migration from Environment Variables

If you previously had TTS configured via environment variables:

### Old Configuration (.env file):
```bash
EAS_TTS_PROVIDER=azure_openai
AZURE_OPENAI_CONFIG='{"endpoint": "https://...", "key": "...", ...}'
```

### New Configuration:
**These environment variables are no longer used!**

Instead:
1. Remove old env vars (optional, they're ignored anyway)
2. Go to web UI: `http://your-server/admin/tts`
3. Configure all settings there
4. Settings are stored in database table `tts_settings`

---

## For Developers: API Request Format

When Azure OpenAI provider is configured, the code sends:

**Request:**
```http
POST https://YOUR-RESOURCE.openai.azure.com/openai/deployments/YOUR-DEPLOYMENT/audio/speech?api-version=2024-03-01-preview
Content-Type: application/json
Authorization: Bearer YOUR_API_KEY

{
  "model": "YOUR-DEPLOYMENT",  // Extracted from endpoint URL!
  "input": "Alert text here",
  "voice": "alloy",
  "speed": 1.0,
  "response_format": "wav"
}
```

**Important:** The `model` parameter uses the deployment name extracted from the URL, NOT the configured model name!

**Expected Response:**
- Status: `200 OK`
- Content-Type: `audio/wav` or `audio/*`
- Body: WAV audio data

---

## Support Resources

### Azure OpenAI Documentation
- [Text-to-Speech Quickstart](https://learn.microsoft.com/en-us/azure/ai-services/openai/text-to-speech-quickstart)
- [API Reference](https://learn.microsoft.com/en-us/azure/ai-services/openai/reference)

### EAS Station™ Documentation
- Repository: https://github.com/KR8MER/eas-station
- Admin UI: `http://your-server/admin/tts`

---

## Summary

**The #1 reason TTS doesn't work:**
- TTS is **disabled by default** after the December 17 migration
- You must **manually enable it** in the web UI at `/admin/tts`
- Environment variables are **no longer used** - configure via web UI only

**Quick fix:**
1. Go to `http://your-server/admin/tts`
2. Enable TTS
3. Select provider
4. Enter credentials with correct endpoint format
5. Save

Use the **"Test TTS"** button in **Admin → Settings → TTS** to verify the credentials work.
