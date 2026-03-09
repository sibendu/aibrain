// ── Environment Variables ─────────────────────────────────
// AZURE_OPENAI_ENDPOINT        e.g. https://YOUR-RESOURCE.openai.azure.com
// AZURE_OPENAI_API_KEY         your Azure OpenAI API key
// AZURE_CHAT_DEPLOYMENT        e.g. gpt-4o-mini
// AZURE_API_VERSION            e.g. 2024-02-01
// PINECONE_API_KEY             your Pinecone API key
// PINECONE_HOST                e.g. https://whatsapp-memory-xxxx.svc.pinecone.io
// WEBHOOK_VERIFY_TOKEN         mybrain_verify_token

// ── Categorize via Azure OpenAI ───────────────────────────

async function categorize(text) {
  const { AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_CHAT_DEPLOYMENT, AZURE_API_VERSION } = process.env;

  const url = `${AZURE_OPENAI_ENDPOINT}/openai/deployments/${AZURE_CHAT_DEPLOYMENT}/chat/completions?api-version=${AZURE_API_VERSION}`;

  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'api-key': AZURE_OPENAI_API_KEY,
    },
    body: JSON.stringify({
      messages: [
        {
          role: 'system',
          content: `You are a message categorizer. Categorize the given message into exactly one of: PERSONAL, WORK, FAMILY, TODO.
Reply with ONLY the category word, nothing else.
Guidelines:
- FAMILY: mentions family members (mom, dad, brother, sister, cousin, parents, etc.)
- WORK: mentions work topics (meeting, deadline, project, boss, client, office, etc.)
- TODO: action items or reminders (buy, pick up, remind, don't forget, need to, task, etc.)
- PERSONAL: everything else`,
        },
        { role: 'user', content: text },
      ],
      max_completion_tokens: 10,
      temperature: 1,
    }),
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Categorize failed: ${res.status} ${err}`);
  }

  const data = await res.json();
  const category = data.choices?.[0]?.message?.content?.trim().toUpperCase();
  const valid = ['PERSONAL', 'WORK', 'FAMILY', 'TODO'];
  return valid.includes(category) ? category : 'PERSONAL';
}

async function storeInPinecone(id, text, metadata) {
  const { PINECONE_HOST, PINECONE_API_KEY } = process.env;

  // ndjson = each record as a separate line
  const record = JSON.stringify({
    _id: id,
    text: text,
    category: metadata.category,
    from: metadata.from,
    timestamp: metadata.timestamp,
  });

  const res = await fetch(`${PINECONE_HOST}/records/namespaces/default/upsert`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-ndjson',
      'Api-Key': PINECONE_API_KEY,
      'X-Pinecone-Api-Version': '2025-10',
    },
    body: record,
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Pinecone upsert failed: ${res.status} ${err}`);
  }

  console.log('Pinecone upsert success');
}

// ── Main Handler ──────────────────────────────────────────

export const handler = async (event) => {
  const method = event.requestContext?.http?.method;

  // Webhook verification
  if (method === 'GET') {
    const p = event.queryStringParameters || {};
    if (p['hub.mode'] === 'subscribe' && p['hub.verify_token'] === process.env.WEBHOOK_VERIFY_TOKEN) {
      console.log('Webhook verified');
      return { statusCode: 200, body: p['hub.challenge'] };
    }
    return { statusCode: 403, body: 'Forbidden' };
  }

  // Incoming WhatsApp message
  if (method === 'POST') {
    const body = JSON.parse(event.body || '{}');
    const message = body.entry?.[0]?.changes?.[0]?.value?.messages?.[0];

    if (message?.text?.body) {
      const text = message.text.body;
      const from = message.from;
      const timestamp = new Date(parseInt(message.timestamp) * 1000).toISOString();
      const id = `msg_${message.id}`;

      console.log(`Received from ${from}: ${text}`);

      // Categorize
      const category = await categorize(text);
      console.log(`Category: ${category}`);

      // Store in Pinecone (Pinecone handles embedding automatically)
      await storeInPinecone(id, text, { category, from, timestamp });
      console.log(`Stored in Pinecone → ${id} [${category}] @ ${timestamp}`);
    }

    return { statusCode: 200, body: 'OK' };
  }

  return { statusCode: 405, body: 'Method Not Allowed' };
};