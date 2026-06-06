(function () {
  const chat = document.getElementById('chat');
  const form = document.getElementById('form');
  const input = document.getElementById('input');
  const send = document.getElementById('send');
  const welcome = document.getElementById('welcome');
  const BOT_NAME = document.querySelector('meta[name="bot-name"]')?.getAttribute('content') || 'Assistant';

  function addMessage(text, role) {
    welcome?.remove();
    const div = document.createElement('div');
    div.className = `msg ${role}`;
    div.textContent = text;
    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = role === 'bot' ? BOT_NAME : 'You';
    div.appendChild(meta);
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
  }

  function showTyping() {
    const div = document.createElement('div');
    div.className = 'typing';
    div.id = 'typing';
    for (let i = 0; i < 3; i++) div.appendChild(document.createElement('span'));
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
  }

  function hideTyping() {
    document.getElementById('typing')?.remove();
  }

  function showError(msg) {
    const div = document.createElement('div');
    div.className = 'error-msg';
    div.textContent = msg;
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
  }

  form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const q = input.value.trim();
    if (!q) return;
    input.value = '';
    send.disabled = true;
    addMessage(q, 'user');
    showTyping();
    try {
      const res = await fetch('/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q }),
      });
      hideTyping();
      if (!res.ok) {
        const err = await res.json();
        showError(err.error || 'Something went wrong.');
        return;
      }
      const data = await res.json();
      addMessage(data.answer + '\n\n—', 'bot');
    } catch (_err) {
      hideTyping();
      showError('Network error — check your connection.');
    } finally {
      send.disabled = false;
      input.focus();
    }
  });
})();
