import { EuiAccordion, EuiIcon } from "@elastic/eui";
import { useState } from "react";

const FAQ = [
  { q: "Does ECM change my clusters or VMs?",
    a: "Discovery only reads. The Proxmox and Elasticsearch clients send GET requests during sync." },
  { q: "What happens to a VM that disappears?",
    a: "ECM deletes VMs, nodes and storage missing from a source on the next successful sync." },
  { q: "Is TLS verified?",
    a: "Yes, by default. Paste a CA certificate, or opt in to skip verification. The opt-in is recorded in the audit log." },
  { q: "Can I see a saved secret again?",
    a: "No. Token secrets and API keys are write-only after you save them." },
  { q: "What does yellow health mean?",
    a: "All primary shards are assigned, but at least one replica is not." },
];

function Row({ id, q, a }: { id: string; q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <EuiAccordion id={id} className="ecm-faq__row" arrowDisplay="none" onToggle={setOpen}
      buttonClassName="ecm-faq__button"
      buttonContent={<span className="ecm-faq__line">
        <span className="ecm-faq__q">{q}</span>
        <EuiIcon type={open ? "minus" : "plus"} aria-hidden="true" className="ecm-faq__icon" />
      </span>}
      paddingSize="none">
      <p className="ecm-faq__a">{a}</p>
    </EuiAccordion>
  );
}

export function Help() {
  return (
    <section id="help" className="ecm-faq" aria-labelledby="help-title">
      <div className="ecm-faq__intro">
        <p className="ecm-pill"><span className="ecm-square ecm-square--small" aria-hidden="true" />Help</p>
        <h2 id="help-title" className="ecm-h2 ecm-h2--large">What ECM reads, stores and removes.</h2>
        <p className="ecm-lede ecm-lede--small">Short answers about sync, certificates and secrets.</p>
      </div>
      <div className="ecm-faq__rows">
        {FAQ.map((f, i) => <Row key={f.q} id={`faq-${i}`} q={f.q} a={f.a} />)}
      </div>
    </section>
  );
}
