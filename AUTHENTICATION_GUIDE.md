# API Authentication Guide

## Overview

The BLE Gateway Server now requires API key authentication for all data endpoints to prevent unauthorized access.

---

## Quick Start

### 1. Start the Server

```bash
python3 ble_gtw_server.py
```

You'll see the API key in the startup output:

```
============================================================
🔐 API Authentication:
============================================================
   ✓ Authentication ENABLED
   API Key: a1b2c3d4...x7y8z9w0

   📱 Configure your Android app:
      Header: Authorization: Bearer a1b2c3d4e5f6g7h8...x7y8z9w0
      Or: X-API-Key: a1b2c3d4e5f6g7h8...x7y8z9w0

   ⚠️  WARNING: Using auto-generated key!
      This key will change on restart.
      Set BLE_GATEWAY_API_KEY env var to persist it.
============================================================
```

**Copy the full API key** (not the masked version) from the startup output.

---

## Setting a Persistent API Key

### Generate a Secure Key

```bash
# Generate a secure 32-character key
export BLE_GATEWAY_API_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

# View your key
echo $BLE_GATEWAY_API_KEY
```

### Persist the Key

**Option A: Add to shell profile (recommended)**
```bash
echo "export BLE_GATEWAY_API_KEY='your-key-here'" >> ~/.bashrc
source ~/.bashrc
```

**Option B: Use systemd environment file**
```bash
# Create environment file
sudo nano /etc/ble-gateway.env

# Add this line:
BLE_GATEWAY_API_KEY=your-key-here

# Reference in systemd service:
EnvironmentFile=/etc/ble-gateway.env
```

**Option C: Docker environment**
```bash
docker run -e BLE_GATEWAY_API_KEY='your-key-here' ble-gateway
```

---

## Using the API Key

### Method 1: Authorization Header (Recommended)

```bash
curl -X POST https://localhost:8443/api/ble \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '[{"id":"AA:BB:CC:DD:EE:FF","name":"Test","rssi":-65}]' \
  -k
```

### Method 2: X-API-Key Header

```bash
curl -X POST https://localhost:8443/api/ble \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '[{"id":"AA:BB:CC:DD:EE:FF","name":"Test","rssi":-65}]' \
  -k
```

### Method 3: Query Parameter (Testing Only)

```bash
curl -X POST "https://localhost:8443/api/ble?api_key=YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '[{"id":"AA:BB:CC:DD:EE:FF","name":"Test","rssi":-65}]' \
  -k
```

---

## Android App Configuration

### Kotlin Example

```kotlin
import okhttp3.*

class BleGatewayClient(private val apiKey: String) {

    private val client = OkHttpClient()
    private val baseUrl = "https://your-server:8443"

    fun sendBleData(devices: List<BleDevice>) {
        val json = Gson().toJson(devices)

        val request = Request.Builder()
            .url("$baseUrl/api/ble")
            .addHeader("Authorization", "Bearer $apiKey")
            .addHeader("Content-Type", "application/json")
            .post(json.toRequestBody("application/json".toMediaType()))
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onResponse(call: Call, response: Response) {
                if (response.isSuccessful) {
                    Log.d("BLE", "Data sent successfully")
                } else {
                    Log.e("BLE", "Error: ${response.code}")
                }
            }

            override fun onFailure(call: Call, e: IOException) {
                Log.e("BLE", "Network error", e)
            }
        })
    }
}
```

### Store API Key Securely

**Option 1: BuildConfig**
```gradle
// In build.gradle
android {
    defaultConfig {
        buildConfigField "String", "API_KEY", "\"${project.findProperty('BLE_API_KEY') ?: 'default'}\""
    }
}

// In gradle.properties (add to .gitignore!)
BLE_API_KEY=your-api-key-here

// In code:
val apiKey = BuildConfig.API_KEY
```

**Option 2: Encrypted SharedPreferences**
```kotlin
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

val masterKey = MasterKey.Builder(context)
    .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
    .build()

val prefs = EncryptedSharedPreferences.create(
    context,
    "ble_settings",
    masterKey,
    EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
    EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
)

prefs.edit().putString("api_key", "your-key-here").apply()
```

---

## Disabling Authentication (Testing Only)

**⚠️ WARNING: Only for local testing! Never disable in production!**

```bash
export BLE_GATEWAY_AUTH_ENABLED=false
python3 ble_gtw_server.py
```

You'll see:
```
🔐 API Authentication:
   ⚠️  Authentication DISABLED (dev mode)
   ⚠️  Anyone can access the API!
```

---

## Protected Endpoints

These endpoints require authentication:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ble` | POST | Submit BLE device data |
| `/api/devices` | GET | Get latest device data |

## Public Endpoints

These endpoints do NOT require authentication:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web dashboard |
| `/health` | GET | Health check |
| `/api/health` | GET | Health check |

---

## Testing Authentication

### Test Without Key (Should Fail)

```bash
curl -X POST https://localhost:8443/api/ble \
  -H "Content-Type: application/json" \
  -d '[{"id":"AA:BB:CC:DD:EE:FF"}]' \
  -k
```

**Expected Response:**
```json
{
  "error": "Unauthorized",
  "message": "Valid API key required. Use Authorization: Bearer <key> or X-API-Key: <key> header."
}
```

### Test With Valid Key (Should Work)

```bash
API_KEY="your-key-from-startup"

curl -X POST https://localhost:8443/api/ble \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '[{"id":"AA:BB:CC:DD:EE:FF","name":"Test","rssi":-65,"advertising":{"temp":23.5}}]' \
  -k
```

**Expected Response:**
```json
{
  "status": "success",
  "received": 1,
  "sensors_detected": 1,
  "timestamp": "2025-11-05 12:00:00"
}
```

---

## Troubleshooting

### "Unauthorized" Error

**Problem:** Getting 401 Unauthorized response

**Solutions:**
1. Check you're using the correct API key from server startup
2. Verify header format: `Authorization: Bearer YOUR_KEY`
3. Make sure key doesn't have extra spaces or quotes
4. Check server logs for "Unauthorized access attempt" messages

### Auto-Generated Key Changes on Restart

**Problem:** Key changes every time server restarts

**Solution:** Set `BLE_GATEWAY_API_KEY` environment variable permanently (see "Setting a Persistent API Key" above)

### Authentication Disabled but Still Getting Errors

**Problem:** Set `AUTH_ENABLED=false` but still getting validation errors

**Solution:** Those are input validation errors, not auth errors. Fix your JSON payload format.

---

## Security Best Practices

### DO ✅

- ✅ Set a persistent API key using environment variables
- ✅ Use HTTPS for all API calls (already enabled)
- ✅ Store API key securely in Android app (EncryptedSharedPreferences)
- ✅ Use Authorization header instead of query parameters
- ✅ Rotate API key periodically (monthly recommended)
- ✅ Monitor server logs for unauthorized attempts

### DON'T ❌

- ❌ Commit API keys to version control
- ❌ Share API keys in plain text
- ❌ Use query parameters in production (visible in logs)
- ❌ Disable authentication on internet-facing servers
- ❌ Reuse API keys across multiple environments

---

## Rotating API Keys

### Step 1: Generate New Key
```bash
NEW_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
echo "New key: $NEW_KEY"
```

### Step 2: Update Server
```bash
export BLE_GATEWAY_API_KEY="$NEW_KEY"
# Restart server
pkill -f ble_gtw_server.py
python3 ble_gtw_server.py
```

### Step 3: Update All Clients
Update the API key in all Android apps and scripts.

---

## Integration with Monitoring

### Health Check (No Auth Required)

```bash
# Check if server is healthy
curl -f https://localhost:8443/health -k

# Expected response:
{
  "status": "healthy",
  "timestamp": "2025-11-05T12:00:00",
  "components": {
    "database": {"status": "healthy", "readings_count": 1234},
    "mqtt": {"status": "connected"}
  }
}
```

Health checks are public so monitoring tools can access them without authentication.

---

## Need Help?

Check the server logs:
```bash
tail -f ble_gateway.log | grep -i "unauthorized\|auth"
```

Common log messages:
- `"Unauthorized access attempt from 192.168.1.100"` - Wrong or missing API key
- `"✓ Authentication ENABLED"` - Auth is active
- `"⚠️ Authentication DISABLED"` - Auth is off (dev mode)

---

**Last Updated:** November 5, 2025
**Version:** 1.0
