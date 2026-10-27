// Sign-in and offline pages: language switch (the same choice the app uses) and the password eye.
(function () {
  var KEY = 'lang';
  var nodes = [].slice.call(document.querySelectorAll('[data-en]'));
  nodes.forEach(function (el) { el.setAttribute('data-ar', el.textContent); });
  var labels = [].slice.call(document.querySelectorAll('[data-en-label]'));
  labels.forEach(function (el) { el.setAttribute('data-ar-label', el.getAttribute('aria-label') || ''); });
  var btn = document.getElementById('auth-lang');

  function apply(lang) {
    var en = lang === 'en';
    document.documentElement.lang = en ? 'en' : 'ar';
    document.documentElement.dir = en ? 'ltr' : 'rtl';
    nodes.forEach(function (el) {
      var v = el.getAttribute(en ? 'data-en' : 'data-ar');
      if (v) el.textContent = v;
    });
    labels.forEach(function (el) { el.setAttribute('aria-label', el.getAttribute(en ? 'data-en-label' : 'data-ar-label')); });
    if (btn) { btn.textContent = en ? 'العربية' : 'English'; btn.lang = en ? 'ar' : 'en'; }
  }
  var current = 'ar';
  try { current = localStorage.getItem(KEY) === 'en' ? 'en' : 'ar'; } catch (e) { /* private mode */ }
  apply(current);
  if (btn) btn.addEventListener('click', function () {
    current = current === 'en' ? 'ar' : 'en';
    try { localStorage.setItem(KEY, current); } catch (e) { /* private mode */ }
    apply(current);
  });

  document.addEventListener('click', function (e) {
    var eye = e.target.closest('[data-eye]');
    if (!eye) return;
    var input = document.getElementById(eye.getAttribute('data-eye'));
    if (!input) return;
    var show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    eye.setAttribute('aria-pressed', show ? 'true' : 'false');
    var i = eye.querySelector('i');
    if (i) { i.classList.toggle('fa-eye', !show); i.classList.toggle('fa-eye-slash', show); }
  });
})();
