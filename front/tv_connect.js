(function () {
  const bar = document.querySelector(".desk-status");
  if (!bar || document.getElementById("tvConnectBtn")) return;

  const button = document.createElement("button");
  button.type = "button";
  button.className = "status-pill tv-connect-btn";
  button.id = "tvConnectBtn";
  button.title = "TradingView";
  button.innerHTML = '<span class="tv-lamp" id="tvLamp" aria-hidden="true"></span>Connect TV';
  bar.prepend(button);

  const overlay = document.createElement("div");
  overlay.className = "tv-modal";
  overlay.id = "tvModal";
  overlay.hidden = true;
  overlay.innerHTML = [
    '<form class="tv-modal-card" id="tvConnectForm">',
    "<h2>Connecter TradingView</h2>",
    "<p>Chrome ou Edge : F12, Application, Cookies, tradingview.com. Copie sessionid et sessionid_sign.</p>",
    '<label>Session ID<input id="tvSession" name="session" type="password" autocomplete="off" spellcheck="false" required></label>',
    '<label>Signature<input id="tvSignature" name="signature" type="password" autocomplete="off" spellcheck="false" required></label>',
    '<p class="tv-form-error" id="tvFormError" role="alert"></p>',
    '<div class="tv-modal-actions">',
    '<button type="button" id="tvConnectCancel">Annuler</button>',
    '<button type="submit" id="tvConnectSubmit">Tester et enregistrer</button>',
    "</div></form>",
  ].join("");
  document.body.appendChild(overlay);

  const lamp = document.getElementById("tvLamp");
  const formError = document.getElementById("tvFormError");
  const submit = document.getElementById("tvConnectSubmit");

  function setConnected(connected, username) {
    lamp.classList.toggle("on", connected);
    button.title = connected
      ? (username ? "TradingView connecté : " + username : "TradingView connecté")
      : "TradingView déconnecté";
  }

  async function refreshStatus() {
    try {
      const response = await fetch("/tv-status");
      const data = await response.json();
      setConnected(Boolean(data.connected));
    } catch (_error) {
      setConnected(false);
    }
  }

  function closeModal() {
    overlay.hidden = true;
    formError.textContent = "";
  }

  button.addEventListener("click", function () {
    formError.textContent = "";
    overlay.hidden = false;
    document.getElementById("tvSession").focus();
  });
  document.getElementById("tvConnectCancel").addEventListener("click", closeModal);
  overlay.addEventListener("click", function (event) {
    if (event.target === overlay) closeModal();
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !overlay.hidden) closeModal();
  });

  document.getElementById("tvConnectForm").addEventListener("submit", async function (event) {
    event.preventDefault();
    formError.textContent = "";
    submit.disabled = true;
    submit.textContent = "Test…";
    const session = document.getElementById("tvSession").value.trim();
    const signature = document.getElementById("tvSignature").value.trim();
    try {
      const response = await fetch("/tv-connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session: session, signature: signature }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        formError.textContent = data.error || "Connexion refusée.";
        if (!data.restored) setConnected(false);
        else refreshStatus();
        return;
      }
      document.getElementById("tvSession").value = "";
      document.getElementById("tvSignature").value = "";
      setConnected(true, data.username || "");
      closeModal();
    } catch (_error) {
      formError.textContent = "Le serveur Kronos ne répond pas.";
    } finally {
      submit.disabled = false;
      submit.textContent = "Tester et enregistrer";
    }
  });

  refreshStatus();
})();
