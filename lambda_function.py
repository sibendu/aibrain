import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ── Environment Variables ─────────────────────────────────
# AZURE_OPENAI_ENDPOINT        e.g. https://YOUR-RESOURCE.openai.azure.com
# AZURE_OPENAI_API_KEY         your Azure OpenAI API key
# AZURE_CHAT_DEPLOYMENT        e.g. gpt-4o-mini
# AZURE_API_VERSION            e.g. 2024-02-01
# PINECONE_API_KEY             your Pinecone API key
# PINECONE_HOST                e.g. https://whatsapp-memory-xxxx.svc.pinecone.io
# WEBHOOK_VERIFY_TOKEN         mybrain_verify_token
# WHATSAPP_TOKEN               your WhatsApp Cloud API token    
# WHATSAPP_PHONE_NUMBER_ID     your phone number ID

# ── HTTP Helper ───────────────────────────────────────────

def http_post(url, headers, body):
    data = json.dumps(body).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, res.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8')


def http_post_raw(url, headers, body_str):
    """For ndjson payloads where body is already a string."""
    data = body_str.encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, res.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8')


# ── Categorize via Azure OpenAI ───────────────────────────

def categorize(text):
    endpoint = os.environ['AZURE_OPENAI_ENDPOINT']
    api_key = os.environ['AZURE_OPENAI_API_KEY']
    deployment = os.environ['AZURE_CHAT_DEPLOYMENT']
    api_version = os.environ['AZURE_API_VERSION']

    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"

    headers = {
        'Content-Type': 'application/json',
        'api-key': api_key,
    }

    body = {
        'messages': [
            {
                'role': 'system',
                'content': (
                    'You are a message categorizer. Categorize the given message into exactly one of: PERSONAL, WORK, FAMILY, TODO.\n'
                    'Reply with ONLY the category word, nothing else.\n'
                    'Guidelines:\n'
                    '- FAMILY: mentions family members (mom, dad, brother, sister, cousin, parents, etc.)\n'
                    '- WORK: mentions work topics (meeting, deadline, project, boss, client, office, etc.)\n'
                    '- TODO: action items or reminders (buy, pick up, remind, don\'t forget, need to, task, etc.)\n'
                    '- PERSONAL: everything else'
                ),
            },
            {
                'role': 'user',
                'content': text,
            },
        ],
        'max_completion_tokens': 10,
        'temperature': 1,
    }

    status, response_text = http_post(url, headers, body)

    if status != 200:
        raise Exception(f"Categorize failed: {status} {response_text}")

    data = json.loads(response_text)
    category = data['choices'][0]['message']['content'].strip().upper()
    valid = ['PERSONAL', 'WORK', 'FAMILY', 'TODO']
    return category if category in valid else 'PERSONAL'


# ── Store in Pinecone ─────────────────────────────────────

def store_in_pinecone(id, text, metadata):
    pinecone_host = os.environ['PINECONE_HOST']
    pinecone_api_key = os.environ['PINECONE_API_KEY']

    url = f"{pinecone_host}/records/namespaces/default/upsert"

    headers = {
        'Content-Type': 'application/x-ndjson',
        'Api-Key': pinecone_api_key,
        'X-Pinecone-Api-Version': '2025-10',
    }

    # ndjson = single record as one line
    record = json.dumps({
        '_id': id,
        'text': text,
        'category': metadata['category'],
        'from': metadata['from'],
        'timestamp': metadata['timestamp'],
    })

    status, response_text = http_post_raw(url, headers, record)

    if status not in (200, 201):
        raise Exception(f"Pinecone upsert failed: {status} {response_text}")

    print('Pinecone upsert success')


# ── Command: Update Brain ─────────────────────────────────────
def update_brain(msg_id, timestamp, from_number, text):
    # Categorize
    category = categorize(text)
    print(f"Category: {category}")

    # Store in Pinecone
    store_in_pinecone(msg_id, text, {
        'category': category,
        'from': from_number,
        'timestamp': timestamp,
    })
    print(f"Stored in Pinecone → {msg_id} [{category}] @ {timestamp}")

# ── Send response to WhatsApp ──────────────────────────────────────────
def send_whatsapp_reply(to_number, reply_text):
    whatsapp_token = os.environ['WHATSAPP_TOKEN']
    phone_number_id = os.environ['WHATSAPP_PHONE_NUMBER_ID']

    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {whatsapp_token}',
    }

    body = {
        'messaging_product': 'whatsapp',
        'to': to_number,
        'type': 'text',
        'text': {
            'body': reply_text,
        },
    }

    status, response_text = http_post(url, headers, body)

    if status not in (200, 201):
        raise Exception(f"WhatsApp reply failed: {status} {response_text}")

    print(f"Reply sent to {to_number}: {reply_text}")

# ── Parse message to detect command ──────────────────────────────────────────
def parse_command(text):
    if text.strip().startswith("/"): 
        command = 'OTHER'
    else:
        command = 'UPDATE_BRAIN'    
    
    return command

# ── Main Handler ──────────────────────────────────────────

def lambda_handler(event, context):

    from_number = None
    method = event.get('requestContext', {}).get('http', {}).get('method')

    # Webhook verification (GET from Meta)
    if method == 'GET':
        params = event.get('queryStringParameters') or {}
        if (
            params.get('hub.mode') == 'subscribe' and
            params.get('hub.verify_token') == os.environ.get('WEBHOOK_VERIFY_TOKEN')
        ):
            print('Webhook verified')
            return {
                'statusCode': 200,
                'body': params.get('hub.challenge', '')
            }
        return {'statusCode': 403, 'body': 'Forbidden'}

    # Incoming WhatsApp message (POST from Meta)
    if method == 'POST':
        responseMessage = 'OK'
        try:
            body = json.loads(event.get('body') or '{}')
            message = body['entry'][0]['changes'][0]['value']['messages'][0]

            if message and message.get('text', {}).get('body'):
                text = message['text']['body']
                from_number = message['from']
                timestamp = datetime.fromtimestamp(
                    int(message['timestamp']), tz=timezone.utc
                ).isoformat()
                msg_id = f"msg_{message['id']}"

                print(f"Received from {from_number}: {text}")

                # Parse the text to map command
                command = parse_command(text)

                # Execute the command                        
                if command == 'UPDATE_BRAIN':                       
                     update_brain(msg_id, timestamp, from_number, text)

                     responseMessage = f"Brain updated" 
                else:
                    print(f"Command: {command}")
                    responseMessage = f"Received command: {command}"

                # Send response back to WhatsApp 
                send_whatsapp_reply(from_number, responseMessage)

                print(f"Processing complete: msg_id {msg_id}, from {from_number}, message: {text}")                    

        except:
            responseMessage = 'Error'
            if from_number is not None:
                try:
                    send_whatsapp_reply(from_number, responseMessage)
                except Exception as e:
                    print(f"Failed to send error reply to WhatsApp: {e}")

        # Whatever happened, send a 200 OK to Meta to avoid retries, since we've already handled the message (either successfully or with an error reply)
        responseMessage = 'OK' 
        return {'statusCode': 200, 'body': responseMessage}    

    return {'statusCode': 405, 'body': 'Method Not Allowed'}