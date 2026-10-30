import React, { useEffect } from "react";
import site from "./site.config.js";

const Mail = () => <a href={`mailto:${site.contactEmail}`}>{site.contactEmail}</a>;

function Privacy() {
  return (<>
    <h1>Privacy policy</h1>
    <p className="updated">Last updated {site.legalUpdated}</p>
    <p>{site.operatorName} ("we", "us") runs {site.siteName} at {site.siteUrl}. This page explains what the service stores and why. Questions go to <Mail />.</p>

    <h2>What we receive</h2>
    <ul>
      <li><b>Code and input you submit.</b> The C or C++ source in the editor, any file you upload, and any program input you type. We need it to compile, run and benchmark your program.</li>
      <li><b>Results we generate.</b> Compiler output, LLVM IR, correctness checks, timings and charts for each experiment, plus the strategy the model selected.</li>
      <li><b>Standard server data.</b> Like any web server, ours or our hosting provider's may record your IP address, request time, requested path and browser type in access logs.</li>
    </ul>
    <p>There are no accounts. We do not ask for your name or email address in order to use the tool.</p>

    <h2>What we do not do</h2>
    <ul>
      <li>We do not run advertising or analytics scripts, and we do not use tracking pixels.</li>
      <li>This site does not set cookies. It does not use browser storage to identify you.</li>
      <li>Fonts are served from our own domain, so your browser does not contact a font provider.</li>
      <li>We do not sell your data.</li>
    </ul>

    <h2>How we use it</h2>
    <p>We use the data above to run the service you asked for, to keep it secure and stable (for example, to investigate abuse or faults), and to train or evaluate the optimisation model only if we tell you so on this page. At the time of writing we do not use submitted code to train the model.</p>

    <h2>How long we keep it</h2>
    <p>Experiment records, including the source you submitted, stay on the server until you delete them with the Delete button in Experiment history, or until we clear the server's storage. Server access logs are kept for a limited period for security and then removed.</p>

    <h2>Who can see it</h2>
    <p>Experiment history is not tied to an account, so do not submit code that contains passwords, keys, personal data or anything confidential. Our hosting provider processes data on our behalf to run the servers. We disclose data to others only when the law requires it.</p>

    <h2>Your rights</h2>
    <p>Depending on where you live, you may have the right to ask what we hold about you, to have it corrected or deleted, and to complain to your data protection authority. Because there are no accounts, we may need details such as an experiment ID to find your records. Write to <Mail />.</p>

    <h2>Changes</h2>
    <p>If this policy changes, we update the date at the top of this page.</p>
  </>);
}

function Terms() {
  return (<>
    <h1>Terms and conditions</h1>
    <p className="updated">Last updated {site.legalUpdated}</p>
    <p>These terms apply when you use {site.siteName} at {site.siteUrl}, run by {site.operatorName} ("we", "us"). By using the service you agree to them. If you do not agree, please do not use it.</p>

    <h2>What the service does</h2>
    <p>You submit C or C++ code. We compile it with several optimisation strategies, check that each build produces the same output, benchmark the builds and show you the measured results.</p>

    <h2>Your code</h2>
    <p>You keep ownership of everything you submit. You give us permission to compile, run, store and display it to you as needed to provide the service. You confirm that you have the right to submit it.</p>

    <h2>Programs are really executed</h2>
    <p>Submitted programs are compiled and run natively on our infrastructure. Limits such as timeouts apply, but they are not a guarantee of isolation. Do not submit code that you would not be willing to run yourself, and do not submit secrets.</p>

    <h2>Acceptable use</h2>
    <p>You must not:</p>
    <ul>
      <li>submit malware, or code meant to damage, probe or gain access to our systems, other users or third-party systems;</li>
      <li>try to escape resource limits, read files you did not submit, or use the service for cryptocurrency mining or other unrelated heavy computation;</li>
      <li>send automated traffic that degrades the service for others;</li>
      <li>submit anything unlawful, or anything you do not have the right to share.</li>
    </ul>
    <p>We may block requests, delete content or restrict access if we believe these rules are broken.</p>

    <h2>Measurements are not promises</h2>
    <p>Timings come from our hardware at the moment of the run and vary with load and configuration. A speedup shown here may not carry over to your machine, your compiler version or your data. The model's pick is a prediction, and the page labels the measured winner separately. Check results before relying on them in production software.</p>

    <h2>Availability and changes</h2>
    <p>We may change, suspend or end the service, or these terms, at any time. If we change the terms, we update the date above. Continued use after a change means you accept it.</p>

    <h2>No warranty</h2>
    <p>The service is provided as it is, without warranties of any kind, to the extent the law allows. We do not promise that it will be uninterrupted, error-free, or that compiled output is correct for your purposes.</p>

    <h2>Limit of liability</h2>
    <p>To the extent the law allows, we are not liable for indirect or consequential loss, lost profits or lost data arising from your use of the service. Nothing in these terms limits liability that cannot be limited by law.</p>

    <h2>Governing law</h2>
    <p>These terms are governed by the law of {site.jurisdiction}, and its courts have jurisdiction, except where mandatory consumer law in your country says otherwise.</p>

    <h2>Contact</h2>
    <p>Questions about these terms: <Mail />. How we handle data is described in the <a href="#/privacy">privacy policy</a>.</p>
  </>);
}

export function LegalPage({ kind }) {
  useEffect(() => { document.title = `${kind === "privacy" ? "Privacy policy" : "Terms and conditions"} | ${site.siteName}`; }, [kind]);
  return (
    <div className="legal-page">
      <header className="legal-top"><b>{site.siteName}</b><a href="#/">Back to the workbench</a></header>
      <article className="legal-body">{kind === "privacy" ? <Privacy /> : <Terms />}</article>
      <footer className="legal-foot"><a href="#/privacy">Privacy policy</a><a href="#/terms">Terms and conditions</a><span>{site.operatorName}</span></footer>
    </div>
  );
}
