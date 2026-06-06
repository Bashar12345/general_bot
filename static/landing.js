(function () {
  const btn = document.getElementById('themeToggle');
  if (!btn) return;
  const html = document.documentElement;
  const stored = localStorage.getItem('landing-theme');
  if (stored === 'dark') html.classList.add('theme-dark');
  btn.textContent = html.classList.contains('theme-dark') ? '🌙' : '☀️';
  btn.addEventListener('click', function () {
    html.classList.toggle('theme-dark');
    const isDark = html.classList.contains('theme-dark');
    localStorage.setItem('landing-theme', isDark ? 'dark' : 'light');
    btn.textContent = isDark ? '🌙' : '☀️';
  });
})();
