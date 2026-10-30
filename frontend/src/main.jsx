import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import App from "./App.jsx";
import { LegalPage } from "./Legal.jsx";
import "./styles.css";

const LEGAL = { "#/privacy": "privacy", "#/terms": "terms" };

function Root() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const f = () => { setHash(window.location.hash); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  const legal = LEGAL[hash];
  // The workbench stays mounted while a legal page is open so a running
  // experiment and unsaved editor text are not lost.
  return (
    <>
      <div hidden={!!legal} className="app-host"><App /></div>
      {legal && <LegalPage kind={legal} />}
    </>
  );
}

createRoot(document.getElementById("root")).render(<Root />);
