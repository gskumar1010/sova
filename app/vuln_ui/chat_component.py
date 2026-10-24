"""Self-contained chat drawer component for SOVA.

Renders as a full-page overlay using st.components.v1.html with height=0
and position:fixed elements that escape the iframe... Actually this uses
a different trick: we render the component at full viewport height in a
hidden/transparent overlay div, passing events back via postMessage.
"""

import json


def build_chat_html(chat_history: list, is_open: bool, logo_b64: str = "") -> str:
    """Build the full chat drawer HTML component."""

    messages_html = ""
    for role, text in reversed(chat_history):
        bubble_class = "msg-user" if role == "user" else "msg-agent"
        avatar = "🧑" if role == "user" else "🤖"
        safe_text = text.replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        messages_html += f"""
        <div class="msg {bubble_class}">
          <div class="msg-avatar">{avatar}</div>
          <div class="msg-bubble">{safe_text}</div>
        </div>"""

    empty_html = "" if chat_history else """
        <div class="empty-state">
          No messages yet.<br>Ask the agent anything about the scan or codebase.
        </div>"""

    drawer_transform = "translateX(0)" if is_open else "translateX(100%)"
    btn_label = "✕ Close" if is_open else "💬 Chat"

    logo_html = (
        f'<img src="data:image/png;base64,{logo_b64}" style="width:28px;height:28px;object-fit:contain;">'
        if logo_b64 else "🛡"
    )

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: transparent; font-family: Inter, -apple-system, sans-serif; overflow: hidden; pointer-events: none; }}
  #chat-fab, #chat-drawer {{ pointer-events: auto; }}

  /* ── Trigger button that lives in the banner area ── */
  #chat-fab {{
    position: fixed;
    top: 0.6rem;
    right: 1.5rem;
    z-index: 99999;
    background: linear-gradient(135deg, #0060aa, #0084cc);
    border: 1px solid rgba(0,180,255,0.4);
    border-radius: 100px;
    padding: 0.32rem 0.9rem;
    font-size: 0.74rem;
    font-weight: 600;
    color: #fff;
    cursor: pointer;
    box-shadow: 0 0 16px rgba(0,132,204,0.35);
    letter-spacing: 0.02em;
    transition: background 0.2s;
  }}
  #chat-fab:hover {{ background: linear-gradient(135deg,#0084cc,#00a0e8); }}

  /* ── Drawer ── */
  #chat-drawer {{
    position: fixed;
    top: 0; right: 0;
    width: 380px;
    height: 100vh;
    background: rgba(5,8,16,0.98);
    border-left: 1px solid rgba(0,180,255,0.22);
    box-shadow: -8px 0 40px rgba(0,0,0,0.6);
    display: flex;
    flex-direction: column;
    z-index: 99998;
    transform: {drawer_transform};
    transition: transform 0.28s cubic-bezier(0.4,0,0.2,1);
  }}

  .drawer-header {{
    background: linear-gradient(90deg,rgba(0,180,255,0.09),rgba(0,180,255,0.03));
    border-bottom: 1px solid rgba(0,180,255,0.15);
    padding: 0.85rem 1.1rem;
    display: flex; align-items: center; gap: 0.6rem;
    font-size: 0.74rem; font-weight: 700;
    letter-spacing: 0.1em; text-transform: uppercase;
    color: #475569;
    flex-shrink: 0;
  }}

  .drawer-input-row {{
    padding: 0.75rem 1rem;
    border-bottom: 1px solid rgba(255,255,255,0.05);
    display: flex; gap: 0.5rem;
    flex-shrink: 0;
  }}
  .drawer-input-row input {{
    flex: 1;
    background: rgba(0,0,0,0.4);
    border: 1px solid rgba(0,180,255,0.2);
    border-radius: 8px;
    color: #e2e8f0;
    font-size: 0.84rem;
    padding: 0.5rem 0.75rem;
    font-family: inherit;
    outline: none;
    transition: border-color 0.2s;
  }}
  .drawer-input-row input:focus {{ border-color: rgba(0,180,255,0.5); }}
  .drawer-input-row input::placeholder {{ color: #334155; }}
  .drawer-input-row button {{
    background: linear-gradient(135deg,#0060aa,#0084cc);
    border: 1px solid rgba(0,180,255,0.3);
    border-radius: 8px;
    color: #fff;
    font-size: 0.78rem;
    font-weight: 600;
    padding: 0.5rem 0.9rem;
    cursor: pointer;
    transition: background 0.2s;
    font-family: inherit;
  }}
  .drawer-input-row button:hover {{ background: linear-gradient(135deg,#0084cc,#00a0e8); }}

  .drawer-messages {{
    flex: 1;
    overflow-y: auto;
    padding: 0.75rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    scrollbar-width: thin;
    scrollbar-color: rgba(0,180,255,0.2) transparent;
  }}

  .msg {{ display: flex; gap: 0.6rem; align-items: flex-start; }}
  .msg-user {{ flex-direction: row-reverse; }}
  .msg-avatar {{
    width: 28px; height: 28px; border-radius: 50%;
    background: rgba(0,180,255,0.1);
    border: 1px solid rgba(0,180,255,0.2);
    display: flex; align-items: center; justify-content: center;
    font-size: 0.8rem; flex-shrink: 0;
  }}
  .msg-bubble {{
    max-width: 80%;
    background: rgba(15,25,45,0.8);
    border: 1px solid rgba(0,180,255,0.1);
    border-radius: 12px;
    padding: 0.55rem 0.85rem;
    font-size: 0.82rem;
    line-height: 1.5;
    color: #cbd5e1;
  }}
  .msg-user .msg-bubble {{
    background: rgba(0,96,170,0.2);
    border-color: rgba(0,180,255,0.2);
  }}
  .empty-state {{
    color: #334155; font-size: 0.8rem;
    text-align: center; padding: 2rem 1rem;
    line-height: 1.6;
  }}
  .typing-indicator {{
    display: flex; gap: 4px; padding: 0.5rem 0;
    align-items: center;
  }}
  .typing-indicator span {{
    width: 6px; height: 6px; border-radius: 50%;
    background: #00b4ff;
    animation: bounce 1.2s infinite;
  }}
  .typing-indicator span:nth-child(2) {{ animation-delay: 0.2s; }}
  .typing-indicator span:nth-child(3) {{ animation-delay: 0.4s; }}
  @keyframes bounce {{
    0%,60%,100% {{ transform: translateY(0); }}
    30% {{ transform: translateY(-6px); }}
  }}
</style>
</head>
<body>

<!-- FAB button — always visible in top-right corner -->
<button id="chat-fab" onclick="toggleDrawer()">{btn_label}</button>

<!-- Slide-out drawer -->
<div id="chat-drawer">
  <div class="drawer-header">
    <span>🤖</span> Agent Chat — Kata VM Sandbox
  </div>
  <div class="drawer-input-row">
    <input id="chat-input" type="text" placeholder="Ask the security agent anything…"
           onkeydown="if(event.key==='Enter')sendMsg()">
    <button onclick="sendMsg()">Send</button>
  </div>
  <div class="drawer-messages" id="messages">
    {empty_html}
    {messages_html}
  </div>
</div>

<script>
  var isOpen = {'true' if is_open else 'false'};

  function toggleDrawer() {{
    isOpen = !isOpen;
    document.getElementById('chat-drawer').style.transform =
      isOpen ? 'translateX(0)' : 'translateX(100%)';
    document.getElementById('chat-fab').textContent = isOpen ? '✕ Close' : '💬 Chat';
    window.parent.postMessage({{type:'sova_chat_toggle', open: isOpen}}, '*');
  }}

  function sendMsg() {{
    var input = document.getElementById('chat-input');
    var msg = input.value.trim();
    if (!msg) return;
    input.value = '';
    // Show typing indicator
    var msgs = document.getElementById('messages');
    var typing = document.createElement('div');
    typing.className = 'typing-indicator';
    typing.innerHTML = '<span></span><span></span><span></span>';
    typing.id = 'typing';
    msgs.prepend(typing);
    // Send to Streamlit via query param
    var url = new URL(window.parent.location.href);
    url.searchParams.set('sova_chat_msg', encodeURIComponent(msg));
    url.searchParams.set('sova_chat_ts', Date.now());
    window.parent.location.href = url.toString();
  }}

  // Keep input focus on load
  document.getElementById('chat-input').focus();
</script>
</body>
</html>
"""
