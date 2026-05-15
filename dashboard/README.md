# BPA CMO Dashboard

Live funnel view from ad spend to closed deal. Marketing tab + Sales tab.
HubSpot is the source of truth; FB is spend; Hyros is cross-check.

## Local development

```bash
cd ~/Desktop/bpa-cmo-agent
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Fill in API keys and pick a DASHBOARD_PASSWORD
pip install -r dashboard/requirements.txt
streamlit run dashboard/app.py
```

Open http://localhost:8501, enter the password.

## Tests

```bash
pytest dashboard/tests -v
```

## Adding a new campaign group

1. Edit `dashboard/config.py` → `CAMPAIGN_GROUPS` regex list.
2. Add the typeform asset(s) → `ASSET_TO_GROUP` mapping.
3. Run pytest.

## Updating HubSpot stage IDs

If HubSpot pipeline stages change:
1. Run `python -m dashboard.probes.hubspot_probe`
2. Update the `STAGES_*` sets in `dashboard/config.py`.
3. Restart the app.

## Deployment

Deployed to Streamlit Community Cloud from this repo, branch `main`.
Secrets are managed in the Streamlit Cloud UI (Settings → Secrets).
