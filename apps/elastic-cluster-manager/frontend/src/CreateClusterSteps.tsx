import {
  EuiButton, EuiDescriptionList, EuiFieldText, EuiFormRow, EuiPanel, EuiStepsHorizontal,
} from "@elastic/eui";
import { useState } from "react";

export const WIZARD_STEPS = ["Name", "Placement", "Sizing", "Roles", "Review", "Apply"] as const;

/**
 * Phase 4 wizard foundation. It holds the choices made so far, never loses them when moving between steps,
 * and never calls the API: applying a plan needs explicit approval and arrives with provisioning.
 * It is built and tested now and deliberately not linked from navigation.
 */
export function CreateClusterSteps() {
  const [step, setStep] = useState(0);
  const [moved, setMoved] = useState(false);
  const [name, setName] = useState("");
  const [version, setVersion] = useState("");
  const last = WIZARD_STEPS.length - 1;
  const go = (n: number) => { setMoved(true); setStep(Math.max(0, Math.min(last, n))); };

  return (
    <section className="ecm-wizard" aria-labelledby="wizard-title">
      <div className="ecm-wizard__top">
        <div>
          <p className="ecm-eyebrow ecm-mono">/ Create cluster</p>
          <h2 id="wizard-title" className="ecm-h2 ecm-h2--large">Create a cluster, one decision at a time.</h2>
          <p className="ecm-lede ecm-lede--small">Review the plan before ECM changes anything.</p>
          <div className="ecm-wizard__actions">
            <EuiButton fill onClick={() => go(step + 1)} isDisabled={step === last}
              aria-describedby={step === last ? "wizard-apply-note" : undefined}>Continue</EuiButton>
            <EuiButton onClick={() => go(step - 1)} isDisabled={step === 0}>Back</EuiButton>
          </div>
          {step === last && (
            <p id="wizard-apply-note" className="ecm-muted">Applying a plan is not available yet.</p>)}
        </div>
        <EuiPanel hasBorder hasShadow={false} paddingSize="l" borderRadius="m" className="ecm-wizard__summary">
          <EuiDescriptionList type="column" compressed listItems={[
            { title: "Name", description: name || "Not set" },
            { title: "Version", description: version || "Not set" },
            { title: "Placement", description: "Not chosen" },
            { title: "Sizing", description: "Not chosen" },
          ]} />
        </EuiPanel>
      </div>

      <div className="ecm-wizard__panels">
        <EuiPanel hasBorder hasShadow={false} paddingSize="l" borderRadius="m"
          className={`ecm-wizard__panel ${moved ? "ecm-step-in" : ""}`} key={`current-${step}`}>
          <span className="ecm-wizard__num">{String(step + 1).padStart(2, "0")}</span>
          <h3 className="ecm-h3 ecm-mono">/ {WIZARD_STEPS[step]}</h3>
          {step === 0 ? (
            <>
              <EuiFormRow label="Cluster name" fullWidth>
                <EuiFieldText fullWidth value={name} onChange={(e) => setName(e.target.value)} />
              </EuiFormRow>
              <EuiFormRow label="Elasticsearch version" fullWidth>
                <EuiFieldText fullWidth value={version} onChange={(e) => setVersion(e.target.value)} />
              </EuiFormRow>
            </>
          ) : <p className="ecm-muted">Choices for this step appear here.</p>}
        </EuiPanel>
        <EuiPanel hasBorder hasShadow={false} paddingSize="l" borderRadius="m" className="ecm-wizard__panel ecm-wizard__panel--next">
          <span className="ecm-wizard__num">{String(Math.min(step + 2, WIZARD_STEPS.length)).padStart(2, "0")}</span>
          <h3 className="ecm-h3 ecm-mono">/ {WIZARD_STEPS[Math.min(step + 1, last)]}</h3>
          <p className="ecm-muted">Up next.</p>
        </EuiPanel>
      </div>

      <EuiStepsHorizontal className="ecm-wizard__strip" steps={WIZARD_STEPS.map((title, i) => ({
        title, status: i < step ? "complete" : i === step ? "current" : "incomplete",
        onClick: () => go(i),
      }))} />
    </section>
  );
}
