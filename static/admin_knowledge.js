(function () {
  let pendingAction = null;

  window.confirmDelete = function (actionUrl, type) {
    const labels = { url: 'URL', pdf: 'PDF', doc: 'document' };
    document.getElementById('deleteModalTitle').textContent =
      'Remove this ' + (labels[type] || 'item') + ' from the index?';
    pendingAction = actionUrl;
    document.getElementById('deleteModal').style.display = 'flex';
  };

  window.closeModal = function () {
    document.getElementById('deleteModal').style.display = 'none';
    pendingAction = null;
  };

  document.getElementById('deleteOnlyBtn').addEventListener('click', function () {
    if (!pendingAction) return;
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = pendingAction;
    document.body.appendChild(form);
    form.submit();
  });

  document.getElementById('deleteAndRebuildBtn').addEventListener('click', function () {
    if (!pendingAction) return;
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = pendingAction;
    const input = document.createElement('input');
    input.type = 'hidden';
    input.name = 'rebuild';
    input.value = '1';
    form.appendChild(input);
    document.body.appendChild(form);
    form.submit();
  });

  document.getElementById('deleteModal').addEventListener('click', function (e) {
    if (e.target === this) closeModal();
  });
})();
