const $ = (s) => document.querySelector(s);

async function signIn() {
  const username = $("#u").value.trim();
  const password = $("#p").value;
  const err = $("#err");
  if (!username || !password) {
    err.textContent = "Enter both fields.";
    err.classList.add("show");
    return;
  }

  $("#go").disabled = true;
  err.textContent = "";
  err.classList.remove("show");
  try {
    const r = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || "Sign in failed");

    sessionStorage.setItem("token", data.token);
    sessionStorage.setItem("user", JSON.stringify(data.user));
    location.href = "/home";
  } catch (e) {
    err.textContent = e.message;
    err.classList.add("show");
    $("#go").disabled = false;
  }
}

$("#go").onclick = signIn;
document.addEventListener("keydown", (e) => {
  if (e.key === "Enter") signIn();
});

// Registered from "/" (not /static/ where the rest of this build's
// assets live) so its default scope covers the whole app - see
// server.py's dedicated /service-worker.js route.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/service-worker.js").catch(() => {});
  });
}
