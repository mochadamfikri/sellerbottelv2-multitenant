"""Opt-in transport. No automatic resend after ambiguous delivery failure.

Reuses tgapi's ambient tenant token and pooled HTTP client. The caller retains
message lifecycle ownership; this adapter never deletes existing messages.
"""
import logging
import os
import httpx
from tgapi import tg

logger = logging.getLogger(__name__)


async def send_table(chat_id, page, kb=None):
    payload = {'chat_id': chat_id}
    if kb is not None:
        payload['reply_markup'] = kb
    enabled = os.environ.get('TELEGRAM_RICH_TABLES_ENABLED', '').lower().strip() in {'1', 'true', 'yes'}
    if enabled:
        try:
            response = await tg('sendRichMessage', **payload,
                                rich_message={'html': page.html, 'skip_entity_detection': True})
        except (httpx.HTTPError, ValueError):
            # Error objects/URLs can include bot tokens: never log them.
            logger.warning('rich_table_delivery_unknown')
            return {'ok': False, 'delivery_status': 'unknown'}
        if not isinstance(response, dict):
            return {'ok': False, 'delivery_status': 'unknown'}
        if response.get('ok'):
            return response
        # Only explicit rejection allows fallback. Auth, rate limit and server
        # failures must not trigger a second request or a hidden retry storm.
        if response.get('error_code') not in {400, 404}:
            return response
        logger.info('rich_table_rejected_using_plain_fallback')
    try:
        return await tg('sendMessage', **payload, text=page.fallback)
    except (httpx.HTTPError, ValueError):
        logger.warning('plain_table_delivery_unknown')
        return {'ok': False, 'delivery_status': 'unknown'}
