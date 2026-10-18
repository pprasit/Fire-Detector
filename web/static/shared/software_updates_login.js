"use strict";
(() => {
  const form = document.getElementById("serverLoginForm"), message = document.getElementById("loginMessage"), button = document.getElementById("signIn");
  const errors = {
    server_login_rejected: "The server did not accept that username or password.",
    administrator_required: "This area requires an active Dashboard administrator account.",
    server_auth_unavailable: "The server sign-in service is unavailable. Please try again later.",
    station_https_required: "Open the HTTPS station address before signing in.",
    approval_rate_limited: "Too many sign-in attempts. Please wait before trying again.",
  };
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const login = document.getElementById("login").value.trim(), field = document.getElementById("password");
    const password = field.value; field.value = ""; button.disabled = true;
    message.textContent = "Verifying your account with the server…";
    try {
      const response = await fetch("/api/software-updates/login", {method:"POST", credentials:"same-origin", cache:"no-store",
        headers:{"Content-Type":"application/json", "X-Update-Intent":"publisher"}, body:JSON.stringify({login,password})});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error);
      if (result.authenticated !== true) throw new Error("invalid_server_response");
      window.location.replace("/software-updates");
    } catch (error) {
      message.textContent = errors[error.message] || "Unable to sign in. Check your connection and try again.";
    } finally { button.disabled = false; }
  });
  window.addEventListener("pagehide", () => { document.getElementById("password").value = ""; });
})();
