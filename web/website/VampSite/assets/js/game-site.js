/*
	Address of the game website (the Evennia web server).

	This is the ONLY place the static site names it. When the game website
	moves, change GAME_SITE_URL below; every link marked with a
	data-game-path attribute is pointed at GAME_SITE_URL + that path.
*/
var GAME_SITE_URL = "https://beckon.vineyard.haus";

(function() {
	"use strict";
	var links = document.querySelectorAll("a[data-game-path]");
	for (var i = 0; i < links.length; i++) {
		links[i].href = GAME_SITE_URL.replace(/\/+$/, "") + links[i].getAttribute("data-game-path");
	}
})();
