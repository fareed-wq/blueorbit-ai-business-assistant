# n8n Workflow Templates

This directory contains sanitized n8n workflow templates for the core
BlueOrbit Automation Lab AI Business Assistant.

These files are intended for learning, portfolio review, and adaptation.
They are not ready to run immediately after import. Credentials, instance-
specific identifiers, pinned test data, calendar identifiers, and selected
sub-workflow references have been removed or replaced with placeholders.

## Included workflows

Import the dependencies before importing the main assistant.

| Import order | File | Purpose |
|---|---|---|
| 1 | `workflows/calendar-availability-tool.json` | Checks calendar availability |
| 2 | `workflows/google-calendar-booking-tool.json` | Creates and tracks demo bookings |
| 3 | `workflows/calendar-slot-finder-tool.json` | Finds and validates candidate demo slots |
| 4 | `workflows/lead-capture-tool.json` | Stores and checks lead records |
| 5 | `workflows/ai-assistant-v1.json` | Main AI assistant and tool orchestration |

## Requirements

- A working n8n instance with compatible versions of the node packages used
  by these exports.
- Google Gemini credentials for the chat model and embedding nodes.
- Google Calendar OAuth credentials with access to a calendar you control.
- Supabase credentials and tables configured for your own project.
- A Header Auth credential for the main webhook.
- A backend configured to call the main n8n webhook, if using the included
  React/FastAPI application.

## Import procedure

1. Back up any existing n8n workflows before making changes.
2. Import the four dependency workflows from `workflows/` first.
3. Import `workflows/ai-assistant-v1.json` last.
4. Open every imported workflow and reconnect its required credentials.
5. In the main assistant, open each Call Workflow tool node and select the
   corresponding imported dependency workflow. The instance-specific workflow
   references were intentionally cleared from these templates.
6. Configure the Google Calendar selectors and Supabase mappings as described
   below.
7. Test each dependency independently with synthetic data before testing the
   main assistant. Keep the imported workflows inactive until configuration
   and testing are complete.

Do not import these templates over your existing working workflows without
backing them up first. The main webhook uses the `ai-chat` path, which may
conflict with an already-active workflow using that path in the same instance.

## Credentials and configuration

### Google Gemini

Select your own Google Gemini credential on both the chat model nodes and
the Google Gemini embeddings node in the main assistant.

Credentials are not included in these exports. Create credentials within
n8n; never place API keys in workflow JSON or commit them to source control.

### Google Calendar

Connect your own Google Calendar OAuth credential to each Google Calendar
node.

The calendar selectors in the templates contain `YOUR_GOOGLE_CALENDAR_ID`.
After importing, select the calendar you intend to use. Review the booking
workflow's Supabase `calendar_id` field mapping and replace its placeholder
with the identifier of that same calendar. Keep those values consistent.

Use a test calendar during setup. Confirm the timezone, availability checks,
event creation, and rollback behavior before using any real booking calendar.

### Supabase

Create your own Supabase credential in n8n and assign it to each Supabase node.

Review each Supabase node's project and table settings, and map the required
columns to your own schema. The booking workflow includes mappings for fields
such as `google_event_id`, `calendar_id`, `name`, `email`, `start_time`,
`end_time`, `timezone`, `status`, and `session_id`. Confirm that your table
contains compatible columns before testing.

The lead capture workflow also uses an n8n Data Table. Its instance-specific
table selection has been cleared from the public template. After importing,
select a Data Table in your own n8n instance and review the `Insert row` column
mappings before testing. The workflow also uses Supabase nodes; verify their
table names, credentials, and column mappings against your own Supabase schema.
Do not assume your database schema matches another installation.

### Main webhook and backend

The main assistant's webhook path is `ai-chat` and uses Header Auth.

Create a new Header Auth credential in n8n using the header name expected by
your backend (`X-BlueOrbit-Chat-Secret`) and a new private secret. Configure
the backend's `N8N_WEBHOOK_URL` and `N8N_WEBHOOK_SECRET` in its local
`backend/.env` file to match the active n8n webhook and credential.

Keep `backend/.env` private and out of Git. Never publish the secret or copy
it into this documentation. Restart the backend after changing environment
variables if necessary.

## Knowledge retrieval

The main assistant uses an in-memory vector store with the key
`blueorbit-company-knowledge`. These five templates do not include the
separate `AI Assistant - Knowledge Ingestion` workflow. A fresh n8n instance
will need its own knowledge-ingestion setup and data before retrieval can
return the BlueOrbit company information. In-memory vector-store contents
may be lost when n8n restarts.

## Testing checklist

- [ ] All five workflows import successfully.
- [ ] Every required credential is connected.
- [ ] All four sub-workflow references in the main assistant point to the
      correct imported workflows.
- [ ] Google Calendar selectors and the Supabase `calendar_id` mapping agree.
- [ ] Supabase tables and columns are mapped to the local schema.
- [ ] Availability checks use the intended timezone and test calendar.
- [ ] Lead capture succeeds and duplicate handling behaves as expected.
- [ ] Booking creates the expected event and handles failures safely.
- [ ] The main webhook accepts an authorized request and rejects requests
      without valid authentication.
- [ ] Knowledge ingestion has been configured and run if using retrieval.

## Security notes

- These are sanitized public templates, not a backup of a live n8n instance.
- Credentials and their bindings are intentionally omitted.
- Pinned execution data, n8n instance IDs, and webhook IDs are omitted.
- Calendar IDs and sub-workflow links must be configured after import.
- Never add credential exports, Google OAuth client-secret files, `.env`
  files, access tokens, or production customer data to this repository.
- Review workflow JSON and its dependencies before adapting it to production.
