import logging
import os

import httpx

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
ALERT_FROM = os.getenv("ALERT_FROM_EMAIL", "alerts@substrack.app")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")


def _build_alert_email(alerts: list) -> tuple[str, str]:
    """Return (subject, html) for a batch of alerts."""
    count = len(alerts)
    subject = f"SubsTrack: {count} upcoming charge{'s' if count != 1 else ''}"

    rows = "".join(
        f"""
        <tr>
          <td style="padding:10px 0;border-bottom:1px solid #e4e4e0;font-size:14px;color:#1a1a18;">{a['merchant']}</td>
          <td style="padding:10px 0;border-bottom:1px solid #e4e4e0;font-size:14px;color:#1a1a18;text-align:right;font-family:monospace;">${a['amount']:.2f}</td>
          <td style="padding:10px 0;border-bottom:1px solid #e4e4e0;font-size:14px;color:#888884;text-align:right;">{a['when']}</td>
        </tr>"""
        for a in alerts
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f5f5f3;font-family:'DM Sans',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f3;padding:40px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid #e4e4e0;border-radius:12px;overflow:hidden;max-width:560px;width:100%;">

        <!-- Header -->
        <tr>
          <td style="padding:24px 32px;border-bottom:1px solid #e4e4e0;">
            <span style="display:inline-block;width:28px;height:28px;background:#1a1a18;color:#fff;border-radius:7px;text-align:center;line-height:28px;font-weight:600;font-size:14px;margin-right:8px;">S</span>
            <span style="font-weight:600;font-size:15px;letter-spacing:-0.02em;vertical-align:middle;">SubsTrack</span>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:28px 32px;">
            <p style="margin:0 0 8px;font-size:20px;font-weight:600;letter-spacing:-0.02em;color:#1a1a18;">
              {count} upcoming charge{'s' if count != 1 else ''}
            </p>
            <p style="margin:0 0 24px;font-size:14px;color:#888884;">
              {'These subscriptions renew' if count != 1 else 'This subscription renews'} within the next 7 days.
            </p>

            <table width="100%" cellpadding="0" cellspacing="0">
              <thead>
                <tr>
                  <th style="text-align:left;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.06em;color:#888884;padding-bottom:8px;">Service</th>
                  <th style="text-align:right;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.06em;color:#888884;padding-bottom:8px;">Amount</th>
                  <th style="text-align:right;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.06em;color:#888884;padding-bottom:8px;">Due</th>
                </tr>
              </thead>
              <tbody>{rows}</tbody>
            </table>
          </td>
        </tr>

        <!-- CTA -->
        <tr>
          <td style="padding:0 32px 28px;">
            <a href="{FRONTEND_URL}" style="display:inline-block;padding:10px 20px;background:#1a1a18;color:#fff;border-radius:8px;text-decoration:none;font-size:14px;font-weight:500;">
              View dashboard
            </a>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="padding:20px 32px;border-top:1px solid #e4e4e0;font-size:12px;color:#888884;">
            You're receiving this because email alerts are enabled for your SubsTrack account.
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

    return subject, html


async def send_alert_email(to: str, alerts: list) -> bool:
    """Send an upcoming-charges email via Resend. Returns True on success."""
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not configured — skipping email to %s", to)
        return False

    subject, html = _build_alert_email(alerts)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"from": ALERT_FROM, "to": [to], "subject": subject, "html": html},
            )
            r.raise_for_status()
            logger.info("Alert email sent to %s (id=%s)", to, r.json().get("id"))
            return True
    except httpx.HTTPStatusError as exc:
        logger.error("Resend rejected email to %s: %s %s", to, exc.response.status_code, exc.response.text)
        return False
    except Exception:
        logger.exception("Failed to send alert email to %s", to)
        return False
