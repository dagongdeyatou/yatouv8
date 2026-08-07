# M9 Google VM corpus

The corpus has two explicit claim classes:

- `archived_real_google_recaptcha_botguard`: the fixed M6 `model.js + enc` path;
- `current_public_loader`: freshly fetched official `api.js` loaders from
  `google.com` and `recaptcha.net`, plus their content-addressed current gstatic
  second stage.

M9 executes each current loader in isolated Chrome (with stage-two network blocked)
and in yatouv8, then requires exact state equality. It does **not** claim that a
current live challenge or current private BotGuard bytecode was executed.
