(() => {
  const article = document.createElement("article");
  article.id = "probe";
  article.classList.add("ready", "m8");
  article.style.cssText = "color: rgb(1, 2, 3); width: 12px";
  article.appendChild(document.createTextNode("yatou"));
  document.body.appendChild(article);

  let events = 0;
  article.addEventListener("click", () => events++, { once: true });
  article.dispatchEvent(new MouseEvent("click"));
  article.dispatchEvent(new MouseEvent("click"));

  const iframe = document.createElement("iframe");
  document.body.appendChild(iframe);
  const result = {
    found: document.querySelector("article#probe.ready") === article,
    text: article.textContent,
    connected: article.isConnected,
    child_count: document.body.childElementCount,
    class_name: article.className,
    color: getComputedStyle(article).color,
    width: getComputedStyle(article).width,
    display: getComputedStyle(article).display,
    events,
    iframe_string_type: typeof iframe.contentWindow.String,
    webdriver: navigator.webdriver,
    platform: navigator.platform,
  };
  article.remove();
  iframe.remove();
  return result;
})()
