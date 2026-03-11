# 🧠 MyBrain — WhatsApp Personal Memory System

A serverless pipeline that captures your WhatsApp messages, categorizes them using Azure OpenAI, stores them as vectors in Pinecone, and lets you query your personal memory via Claude using MCP.

## Architecture

```
WhatsApp Message
      ↓
Meta Cloud API
      ↓ (webhook POST)
AWS API Gateway (public HTTPS endpoint)
      ↓
Lambda A — whatsapp-receiver (returns 200 instantly)
      ↓ (async invoke)
Lambda B — whatsapp-processor
      ↓                        ↓
Azure OpenAI              Pinecone Vector DB
(categorize message)      (store text + metadata)
      ↓
WhatsApp Reply sent back to sender
      ↓
Claude Desktop via MCP
(query your stored memories)
```

## Categories

Every incoming WhatsApp message is automatically categorized into one of:

| Category | Description |
|---|---|
| `PERSONAL` | General personal messages |
| `WORK` | Work-related topics, meetings, deadlines |
| `FAMILY` | Messages mentioning family members |
| `TODO` | Action items, reminders, tasks |

---

## Prerequisites

- [AWS Account](https://aws.amazon.com/free/)
- [Meta Developer Account](https://developers.facebook.com/)
- [Azure OpenAI resource](https://azure.microsoft.com/en-us/products/ai-services/openai-service)
- [Pinecone Account](https://pinecone.io) (free tier)
- [Claude Desktop](https://claude.ai/download) (for MCP querying)
- Node.js installed locally (for MCP server)

---

## Part 1: Meta WhatsApp Setup

> 📖 [Meta WhatsApp Cloud API Docs](https://developers.facebook.com/docs/whatsapp/cloud-api)

### 1.1 Create a Meta Developer App

1. Go to [developers.facebook.com](https://developers.facebook.com) → **Create App**
2. Select use case filter: **Business messaging**
3. Choose **"Connect with customers through WhatsApp"**
4. Complete the app creation wizard
5. You will land on the app **Dashboard**

### 1.2 Get Your Test Phone Number & Credentials

1. Left sidebar → **WhatsApp → API Setup**
2. Note down:
   - **Phone Number ID** (e.g. `1008113499059205`)
   - **WhatsApp Business Account ID**
3. Click **"Generate access token"** → select your WhatsApp Business account → copy the token

> ⚠️ The token from API Setup expires in 24 hours. For production, create a permanent token via a System User in [Meta Business Manager](https://business.facebook.com) → Settings → Users → System Users.

### 1.3 Add Test Recipient

Since the app is unpublished, only approved numbers can receive messages:

1. WhatsApp → API Setup → **"To"** dropdown → **"Manage phone number list"**
2. Add your personal WhatsApp number
3. Verify via OTP sent to your WhatsApp

### 1.4 Configure Webhook (done after Lambda setup)

1. Left sidebar → **WhatsApp → Configuration**
2. Under **Webhook** → click **Edit**
3. Fill in:
   - **Callback URL**: your API Gateway URL (e.g. `https://xxxxx.execute-api.ap-south-1.amazonaws.com/prod/webhook`)
   - **Verify Token**: your chosen verify token (e.g. `mybrain_verify_token`)
4. Click **Verify and Save**
5. Scroll down to **Webhook Fields** → toggle **`messages`** to **Subscribed**

> 📖 [Webhook Setup Guide](https://developers.facebook.com/docs/whatsapp/cloud-api/guides/set-up-webhooks)

---

## Part 2: Pinecone Setup

> 📖 [Pinecone Docs](https://docs.pinecone.io)

### 2.1 Create Account & Index

1. Sign up at [pinecone.io](https://pinecone.io) (free Starter plan)
2. Click **"Create Index"**
3. Configure:
   - **Name**: `whatsapp-memory`
   - **Integrated embedding**: ✅ enabled
   - **Embedding model**: `multilingual-e5-large` (free, hosted by Pinecone)
   - **Metric**: `cosine`
   - **Capacity mode**: Serverless
4. Click **Create Index**

### 2.2 Collect Credentials

From your Pinecone dashboard:
- **API Key**: Left sidebar → **API Keys** → copy
- **Index Host URL**: Click your index → copy the Host URL (e.g. `https://whatsapp-memory-xxxx.svc.pinecone.io`)

> 📖 [Pinecone Integrated Inference](https://docs.pinecone.io/guides/inference/integrated-inference)

---

## Part 3: AWS Lambda Setup

> 📖 [AWS Lambda Docs](https://docs.aws.amazon.com/lambda/)

### 3.1 Create Lambda A — whatsapp-receiver

This Lambda receives the webhook from Meta and immediately returns `200 OK`, then asynchronously invokes the processor Lambda to avoid Meta retries.

1. AWS Console → **Lambda** → **Create function**
2. Settings:
   - **Name**: `whatsapp-receiver`
   - **Runtime**: Python 3.12
   - **Architecture**: x86_64
3. Paste the receiver code (see `lambda_receiver.py`)
4. **Configuration → General configuration**: set **Timeout to 10 seconds**
5. **Configuration → Handler**: set to `lambda_receiver.handler`

#### Environment Variables for whatsapp-receiver

| Variable | Description | Example |
|---|---|---|
| `WEBHOOK_VERIFY_TOKEN` | Token you chose for Meta webhook verification | `mybrain_verify_token` |
| `PROCESSOR_FUNCTION_NAME` | Name of the processor Lambda | `whatsapp-processor` |

#### IAM Permission

Add this inline policy to the receiver Lambda's execution role so it can invoke the processor:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "arn:aws:lambda:YOUR_REGION:YOUR_ACCOUNT_ID:function:whatsapp-processor"
    }
  ]
}
```

### 3.2 Create Lambda B — whatsapp-processor

This Lambda does the actual work: categorizes the message, stores it in Pinecone, and sends a WhatsApp reply.

1. AWS Console → **Lambda** → **Create function**
2. Settings:
   - **Name**: `whatsapp-processor`
   - **Runtime**: Python 3.12
   - **Architecture**: x86_64
3. Paste the processor code (see `lambda_brain_processor.py`)
4. **Configuration → General configuration**: set **Timeout to 30 seconds**
5. **Configuration → Handler**: set to `lambda_brain_processor.handler`

#### Environment Variables for whatsapp-processor

| Variable | Description | Example |
|---|---|---|
| `AZURE_OPENAI_ENDPOINT` | Your Azure OpenAI resource endpoint | `https://YOUR-RESOURCE.openai.azure.com` |
| `AZURE_OPENAI_API_KEY` | Your Azure OpenAI API key | `abc123...` |
| `AZURE_CHAT_DEPLOYMENT` | Your deployed chat model name | `gpt-4o-mini` |
| `AZURE_API_VERSION` | Azure OpenAI API version | `2024-02-01` |
| `PINECONE_API_KEY` | Your Pinecone API key | `pcsk_...` |
| `PINECONE_HOST` | Your Pinecone index host URL | `https://whatsapp-memory-xxxx.svc.pinecone.io` |
| `WHATSAPP_TOKEN` | Meta access token | `EAAm...` |
| `WHATSAPP_PHONE_NUMBER_ID` | Your WhatsApp test phone number ID | `1008113499059205` |

> 📖 [Lambda Environment Variables](https://docs.aws.amazon.com/lambda/latest/dg/configuration-envvars.html)

### 3.3 Create API Gateway

> 📖 [API Gateway HTTP API Docs](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api.html)

1. AWS Console → **API Gateway** → **Create API**
2. Choose **HTTP API** → **Build**
3. **Add integration** → Lambda → select `whatsapp-receiver`
4. **API name**: `whatsapp-api` → Next
5. Create two routes:
   - `GET /webhook` → integrated with `whatsapp-receiver`
   - `POST /webhook` → integrated with `whatsapp-receiver`
6. **Deploy** → Stage name: `prod`
7. Copy the **Invoke URL**: `https://xxxxx.execute-api.YOUR_REGION.amazonaws.com/prod`
8. Your full webhook URL: `https://xxxxx.execute-api.YOUR_REGION.amazonaws.com/prod/webhook`

---

## Part 4: MCP Integration with Claude Desktop

> 📖 [Pinecone MCP Server](https://github.com/pinecone-io/pinecone-mcp)
> 📖 [Claude MCP Docs](https://docs.anthropic.com/en/docs/claude-code/mcp)

### 4.1 Find Claude Desktop Config File

**Windows:**
```
C:\Users\YOUR_USERNAME\AppData\Roaming\Claude\claude_desktop_config.json
```

**Mac:**
```
~/Library/Application Support/Claude/claude_desktop_config.json
```

### 4.2 Add Pinecone MCP Server

```json
{
  "mcpServers": {
    "pinecone": {
      "command": "npx",
      "args": ["-y", "@pinecone-database/mcp"],
      "env": {
        "PINECONE_API_KEY": "your-pinecone-api-key-here"
      }
    }
  }
}
```

### 4.3 Restart Claude Desktop

Fully quit and reopen Claude Desktop. Look for the **🔨 hammer icon** in the chat input — this confirms MCP tools are loaded.

### 4.4 Example Queries

Ask Claude:

- *"Search my whatsapp-memory index for messages about my family"*
- *"Find all TODO items I received on WhatsApp"*
- *"What work-related messages have I stored?"*
- *"Show me everything Sibendu sent about meetings"*

---

## Project Files

| File | Description |
|---|---|
| `lambda_receiver.py` | Lambda A — receives webhook, returns 200, async invokes processor |
| `lambda_brain_processor.py` | Lambda B — categorizes, stores in Pinecone, sends WhatsApp reply |

---

## Flow Summary

```
1. You send a WhatsApp message to the test number (+1 555 636 5266)
2. Meta Cloud API fires a POST to your API Gateway webhook URL
3. whatsapp-receiver returns 200 OK immediately (prevents Meta retries)
4. whatsapp-receiver async invokes whatsapp-processor
5. whatsapp-processor calls Azure OpenAI to categorize the message
6. whatsapp-processor stores the message + category + timestamp in Pinecone
7. whatsapp-processor sends a reply back to your WhatsApp
8. Later, Claude Desktop queries Pinecone via MCP to retrieve your memories
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| Meta sends message multiple times | Lambda taking too long, Meta retries | Use async pattern (Lambda A → Lambda B) |
| `ENOTFOUND` error | Wrong URL format in env var | Make sure endpoint includes `https://` |
| `max_tokens` error | Model doesn't support `max_tokens` | Use `max_completion_tokens` instead |
| Pinecone 404 error | Wrong API endpoint path | Use `/records/namespaces/default/upsert` |
| Pinecone 400 `Missing field_mapping` | Wrong field name | Use `text` field (matches your index field map) |
| WhatsApp reply `not in allowed list` | App is unpublished | Add recipient number in API Setup → Manage phone number list |
| Lambda timeout | Default 3s too short | Increase timeout to 30s in Configuration |
| MCP `integrated inference` error | Index created without integrated embedding | Recreate index with `multilingual-e5-large` model |

---

## Useful Links

- [Meta WhatsApp Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api)
- [Meta Webhook Setup](https://developers.facebook.com/docs/whatsapp/cloud-api/guides/set-up-webhooks)
- [Meta Business Manager](https://business.facebook.com)
- [AWS Lambda Developer Guide](https://docs.aws.amazon.com/lambda/latest/dg/welcome.html)
- [AWS API Gateway HTTP API](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api.html)
- [AWS CloudWatch Logs](https://docs.aws.amazon.com/lambda/latest/dg/monitoring-cloudwatchlogs.html)
- [Pinecone Quickstart](https://docs.pinecone.io/guides/get-started/quickstart)
- [Pinecone Integrated Inference](https://docs.pinecone.io/guides/inference/integrated-inference)
- [Pinecone MCP Server](https://github.com/pinecone-io/pinecone-mcp)
- [Azure OpenAI Service](https://learn.microsoft.com/en-us/azure/ai-services/openai/)
- [Claude MCP Documentation](https://docs.anthropic.com/en/docs/claude-code/mcp)
