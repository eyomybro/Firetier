const T = ["preset-rivals-notex", "preset-rivals-fps", "preset-balanced", "preset-vulkan", "preset-d3d11", "preset-opengl", "user", "imported", "game-all"];
const I = ["empty-profiles", "empty-search", "error-target", "empty-assets", "empty-log", "welcome"];
const fig = (src, name, cls = "") =>
  `<figure class="${cls}"><img src="${src}" alt=""><figcaption>${name}<span class="badge outline">hand-made SVG</span></figcaption></figure>`;
document.getElementById("thumbs").innerHTML = T.map(n => fig(`../web/assets/thumbs/${n}.svg`, n)).join("");
document.getElementById("illus").innerHTML = I.map(n => fig(`../web/assets/illus/${n}.svg`, n, "ill")).join("");
