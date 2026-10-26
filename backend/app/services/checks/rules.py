"""Deterministic check implementations, keyed by RuleVersion.check_type.

Each function returns Outcomes that cite the exact rule version, the document
version/field (with page + bbox) and, for external checks, the SourceCheck row.
"""
from __future__ import annotations

from datetime import timedelta
from difflib import SequenceMatcher

from ...models import ChecklistItem, Document, DocumentVersion, RuleVersion, SourceCheck
from .. import extraction as X
from ..connectors import aicte_records, crossref, scopus
from .context import Ctx, Outcome, doc_label, ev_declared, ev_doc, ev_field, ev_rule, type_label

# ------------------------------------------------------------------ completeness


def checklist_completeness(ctx: Ctx, rv: RuleVersion) -> list[Outcome]:
    out = []
    items: list[ChecklistItem] = ctx.app.category.checklist
    present = {d.document_type for d, _ in ctx.docs}
    for it in items:
        fp = f"checklist:{it.document_type}"
        if it.document_type in present:
            d, v = ctx.of_type(it.document_type)[0]
            out.append(Outcome(fp, "completeness", f"{it.label} submitted", "verified", False,
                               f"At least one document of type '{it.label}' is present.", "n/a", rv.severity,
                               v.id, document_type=it.document_type, method="Checklist presence check",
                               evidence=[ev_doc(d, v), ev_rule(rv)]))
        elif it.mandatory:
            out.append(Outcome(
                fp, "completeness", f"Mandatory document missing: {it.label}", "missing", True,
                f"The {ctx.app.category.name} checklist requires '{it.label}', but no document of this type was submitted.",
                "confirmed", rv.severity, document_type=it.document_type, field="document",
                expected_value=it.label, extracted_value="(not submitted)", method="Checklist presence check",
                evidence=[ev_rule(rv), {"type": "checklist", "label": it.label, "guidance": it.guidance}],
                recommended_action=f"Request the institution to upload the {it.label}.",
                institution_text=f"The mandatory document '{it.label}' was not found in your submission. {it.guidance}".strip(),
            ))
    return out


def required_fields(ctx: Ctx, rv: RuleVersion) -> list[Outcome]:
    """params: {document_type: str, fields: [..]}"""
    out = []
    dt = rv.params.get("document_type", "")
    for d, v in ctx.of_type(dt):
        if v.processing_status != "processed":
            continue
        missing = [f for f in rv.params.get("fields", []) if not ctx.first(v, f)]
        fp = f"fields:{dt}:doc{d.id}"
        if missing:
            labels = ", ".join(m.replace("_", " ") for m in missing)
            out.append(Outcome(
                fp, "completeness", f"Incomplete mandatory fields in {d.title}", "missing", True,
                f"The following mandatory field(s) could not be found in the document text: {labels}.",
                "inconclusive" if v.text_method == "ocr" else "confirmed", rv.severity, v.id, document_type=dt,
                field=labels, extracted_value="(not found)", expected_value=labels,
                method=f"Label-based field extraction ({v.text_method})",
                limitations="A field may be present but printed in a layout the extractor does not recognise; open the document to confirm.",
                evidence=[ev_doc(d, v), ev_rule(rv)],
                recommended_action="Open the document and confirm whether the fields are present; if absent, request a complete document.",
                institution_text=f"'{d.title}' does not show the following required detail(s): {labels}.",
            ))
        else:
            out.append(Outcome(fp, "completeness", f"Mandatory fields present in {d.title}", "verified", False,
                               "All mandatory fields were located.", "n/a", rv.severity, v.id, document_type=dt,
                               method="Label-based field extraction", evidence=[ev_doc(d, v), ev_rule(rv)]))
    return out


# ------------------------------------------------------------------ validity


def validity(ctx: Ctx, rv: RuleVersion) -> list[Outcome]:
    out = []
    warn_days = int(rv.params.get("expiring_soon_days", 60))
    types = {it.document_type for it in ctx.app.category.checklist if it.requires_validity}
    for d, v in ctx.docs:
        if d.document_type not in types or v.processing_status != "processed":
            continue
        fp = f"validity:doc{d.id}"
        exp_f = ctx.first(v, "expiry_date")
        iss_f = ctx.first(v, "issue_date")
        base_ev = [ev_rule(rv)]
        if not exp_f:
            out.append(Outcome(
                fp, "validity", f"Validity period not found: {d.title}", "manual_review", True,
                "This document type must state a validity period, but no expiry/valid-until date was extracted.",
                "inconclusive", rv.severity, v.id, document_type=d.document_type, field="expiry_date",
                extracted_value="(not found)", method="Date extraction", evidence=[ev_doc(d, v)] + base_ev,
                recommended_action="Inspect the document; if no validity date is stated, request a document that shows it.",
                institution_text=f"The validity period of '{d.title}' could not be determined from the submitted copy.",
            ))
            continue
        exp = X.parse_date(exp_f.effective_value)
        ev = [ev_field(d, v, exp_f)] + ([ev_field(d, v, iss_f)] if iss_f else []) + base_ev
        conf_note = f"Extracted by {exp_f.method}" + (f", OCR confidence {exp_f.ocr_confidence}" if exp_f.ocr_confidence is not None else "")
        if not exp:
            out.append(Outcome(fp, "validity", f"Unparseable validity date: {d.title}", "manual_review", True,
                               f"The validity value '{exp_f.effective_value}' could not be read as a date.", "inconclusive",
                               rv.severity, v.id, document_type=d.document_type, field="expiry_date",
                               extracted_value=exp_f.effective_value, method="Date parsing", evidence=ev,
                               recommended_action="Confirm the date manually in the extracted-field panel.",
                               institution_text=f"The validity date on '{d.title}' is not legible."))
            continue
        iss = X.parse_date(iss_f.effective_value) if iss_f else None
        if iss and iss > exp:
            out.append(Outcome(fp + ":order", "validity", f"Inconsistent dates: {d.title}", "mismatch", True,
                               f"Issue date {iss.isoformat()} is later than the expiry date {exp.isoformat()}.", "confirmed",
                               "high", v.id, document_type=d.document_type, field="issue_date / expiry_date",
                               extracted_value=f"issued {iss.isoformat()}", expected_value=f"on or before {exp.isoformat()}",
                               method="Date order rule", evidence=ev, confidence_note=conf_note,
                               recommended_action="Request a clarification or a corrected certificate.",
                               institution_text=f"The issue and expiry dates on '{d.title}' are inconsistent."))
        uncertain = exp_f.method == "ocr" and exp_f.confirmed_value is None and exp_f.needs_confirmation
        if exp < ctx.ref_date:
            out.append(Outcome(
                fp, "validity", f"Expired: {d.title}", "expired", True,
                f"The document states validity until {exp.isoformat()}, which is before the scrutiny reference date {ctx.ref_date.isoformat()}.",
                "inconclusive" if uncertain else "confirmed", rv.severity, v.id, document_type=d.document_type,
                field="expiry_date", extracted_value=exp_f.effective_value, expected_value=f"on or after {ctx.ref_date.isoformat()}",
                method="Validity date compared with reference date", evidence=ev, confidence_note=conf_note,
                limitations="Low-confidence OCR value; confirm the date before relying on it." if uncertain else "",
                recommended_action=f"Request a renewed {type_label(d.document_type)} valid for the academic year.",
                institution_text=f"'{d.title}' expired on {exp.strftime('%d %b %Y')}. Submit a currently valid {type_label(d.document_type)}.",
            ))
        else:
            days = (exp - ctx.ref_date).days
            note = f"Valid for {days} more days." + (" Expiring soon." if days <= warn_days else "")
            out.append(Outcome(fp, "validity", f"Within validity: {d.title}", "verified", False,
                               f"Valid until {exp.isoformat()}. {note}", "n/a", rv.severity, v.id,
                               document_type=d.document_type, field="expiry_date", extracted_value=exp_f.effective_value,
                               method="Validity date compared with reference date", evidence=ev,
                               confidence_note=("expiring_soon" if days <= warn_days else "")))
    return out


# ------------------------------------------------------------------ extraction quality


def extraction_quality(ctx: Ctx, rv: RuleVersion) -> list[Outcome]:
    out = []
    thr = float(rv.params.get("min_ocr_confidence", 70))
    for d, v in ctx.docs:
        fp = f"legibility:doc{d.id}"
        if v.processing_status == "failed":
            out.append(Outcome(fp, "extraction", f"Document could not be processed: {d.title}", "manual_review", True,
                               f"Processing failed: {v.processing_error}", "inconclusive", "high", v.id,
                               document_type=d.document_type, method="Document processing", evidence=[ev_doc(d, v), ev_rule(rv)],
                               recommended_action="Open the original file. If corrupt or unreadable, request a fresh copy.",
                               institution_text=f"'{d.title}' could not be opened or read. Upload a clear, unprotected PDF."))
            continue
        if d.document_type == "infrastructure_photo":
            continue
        if v.text_method == "none" or len(v.extracted_text.strip()) < 30:
            out.append(Outcome(fp, "extraction", f"Unreadable or insufficient text: {d.title}", "manual_review", True,
                               "No usable text could be extracted (native or OCR).", "inconclusive", rv.severity, v.id,
                               document_type=d.document_type, method=v.text_method or "none",
                               evidence=[ev_doc(d, v), ev_rule(rv)], recommended_action="Inspect visually; request a legible copy if needed.",
                               institution_text=f"'{d.title}' is not legible. Upload a clearer scan (300 dpi recommended)."))
            continue
        low = [f for f in v.fields if f.needs_confirmation and f.confirmed_value is None]
        if v.text_method == "ocr" and ((v.ocr_mean_confidence or 0) < thr or low):
            out.append(Outcome(
                fp, "extraction", f"Low-confidence OCR values need confirmation: {d.title}", "manual_review", True,
                f"Scanned document; mean OCR word confidence {v.ocr_mean_confidence}. {len(low)} key value(s) are below the confirmation threshold.",
                "inconclusive", "low", v.id, document_type=d.document_type, method="Tesseract OCR",
                confidence_note=f"Tesseract mean word confidence {v.ocr_mean_confidence} (0–100 scale reported by the engine)",
                evidence=[ev_field(d, v, f) for f in low[:8]] + [ev_rule(rv)],
                limitations="OCR confidence is the engine's own estimate and is not a probability of correctness.",
                recommended_action="Confirm or correct the flagged values in the extracted-field panel.",
            ))
        else:
            out.append(Outcome(fp, "extraction", f"Text extracted: {d.title}", "verified", False,
                               f"Text extracted using {v.text_method} method; no values require confirmation.", "n/a", "low", v.id,
                               document_type=d.document_type, method=v.text_method, evidence=[ev_doc(d, v)]))
        basis = v.classification_basis or {}
        if basis.get("agrees_with_declared") is False:
            out.append(Outcome(
                f"classification:doc{d.id}", "extraction", f"Content does not match declared type: {d.title}", "manual_review", True,
                f"Declared as '{type_label(d.document_type)}' but the text most resembles '{type_label(basis.get('best_type', ''))}'.",
                "suspected", "medium", v.id, document_type=d.document_type, field="document_type",
                extracted_value=type_label(basis.get("best_type", "")), expected_value=type_label(d.document_type),
                method="Keyword classification", evidence=[ev_doc(d, v, "Matched keywords: " + str(basis.get("matches")))],
                limitations="Keyword classification is approximate and may misjudge unusual layouts.",
                recommended_action="Check whether the correct file was uploaded under this category.",
                institution_text=f"The file uploaded as '{type_label(d.document_type)}' appears to be a different document.",
            ))
    return out


# ------------------------------------------------------------------ cross-document


def field_consistency(ctx: Ctx, rv: RuleVersion) -> list[Outcome]:
    """params: {field: institution_name | permanent_id}"""
    out = []
    fname = rv.params["field"]
    declared = (ctx.app.declared or {}).get(fname, "")
    label = fname.replace("_", " ")
    if not declared:
        return out
    dnorm = X.normalize_field(fname, declared)
    for d, v in ctx.docs:
        for f in ctx.fields(v, fname)[:1]:
            fp = f"xdoc:{fname}:doc{d.id}"
            val = f.effective_value
            vn = X.normalize_field(fname, val) if f.confirmed_value is not None else f.normalized_value
            ev = [ev_declared(fname, declared), ev_field(d, v, f), ev_rule(rv)]
            if vn == dnorm:
                out.append(Outcome(fp, "cross_document", f"{label.capitalize()} matches: {d.title}", "verified", False,
                                   f"The {label} on this document matches the application form.", "n/a", rv.severity, v.id,
                                   document_type=d.document_type, field=fname, extracted_value=val, expected_value=declared,
                                   method="Normalised exact comparison", evidence=ev))
                continue
            sim = round(SequenceMatcher(None, vn, dnorm).ratio(), 3)
            uncertain = f.method == "ocr" and f.needs_confirmation and f.confirmed_value is None
            out.append(Outcome(
                fp, "cross_document", f"{label.capitalize()} differs: {d.title}", "manual_review" if uncertain else "mismatch", True,
                f"The {label} extracted from {doc_label(d)} ('{val}') differs from the value declared in the application ('{declared}'). "
                f"Neither record is assumed to be correct.",
                "inconclusive" if uncertain else "confirmed", rv.severity, v.id, document_type=d.document_type, field=fname,
                extracted_value=val, expected_value=declared, method=f"Normalised comparison (character similarity {sim})",
                confidence_note=f"Character similarity {sim} after normalisation" + (f"; OCR confidence {f.ocr_confidence}" if f.ocr_confidence else ""),
                limitations="A small difference may reflect an OCR error; confirm the extracted value first." if uncertain else "",
                evidence=ev, recommended_action="Ask the institution to explain the difference or submit a corrected document.",
                institution_text=f"The {label} shown on '{d.title}' (\"{val}\") does not match the {label} declared in the application (\"{declared}\").",
            ))
    return out


def intake_consistency(ctx: Ctx, rv: RuleVersion) -> list[Outcome]:
    out = []
    declared = str((ctx.app.declared or {}).get("approved_intake", ""))
    prev = ctx.of_type("previous_approval")
    intake_docs = ctx.of_type("intake_details")
    if intake_docs:
        d, v = intake_docs[0]
        rows = ctx.fields(v, "programme_intake")
        total_f = ctx.first(v, "approved_intake")
        s = sum(int(r.normalized_value or 0) for r in rows if (r.normalized_value or "").isdigit())
        if rows and total_f and total_f.normalized_value.isdigit() and int(total_f.normalized_value) != s:
            out.append(Outcome(f"intake:sum:doc{d.id}", "cross_document", "Programme-wise intake does not add up", "mismatch", True,
                               f"Programme rows sum to {s}, but the stated total is {total_f.effective_value}.", "confirmed", rv.severity,
                               v.id, document_type=d.document_type, field="approved_intake", extracted_value=total_f.effective_value,
                               expected_value=str(s), method="Arithmetic check",
                               evidence=[ev_field(d, v, total_f)] + [ev_field(d, v, r) for r in rows] + [ev_rule(rv)],
                               recommended_action="Request a corrected intake statement.",
                               institution_text=f"In '{d.title}', the programme-wise intake figures add up to {s}, not {total_f.effective_value}."))
    if prev and declared:
        d, v = prev[0]
        f = ctx.first(v, "approved_intake")
        fp = f"intake:prev:doc{d.id}"
        if f and f.normalized_value.isdigit():
            ev = [ev_declared("approved_intake", declared), ev_field(d, v, f), ev_rule(rv)]
            if int(declared) > int(f.normalized_value) and ctx.app.category.code == "EOA":
                out.append(Outcome(fp, "cross_document", "Declared intake exceeds previously approved intake", "mismatch", True,
                                   f"The application declares an intake of {declared}, but the previous approval letter shows {f.effective_value}. "
                                   "An increase is not processed under Extension of Approval.", "confirmed", rv.severity, v.id,
                                   document_type="previous_approval", field="approved_intake", extracted_value=declared,
                                   expected_value=f"≤ {f.effective_value}", method="Numeric comparison", evidence=ev,
                                   recommended_action="Ask the institution to correct the declared intake or apply under the appropriate category.",
                                   institution_text=f"The intake declared in the application ({declared}) exceeds the intake in the previous approval letter ({f.effective_value})."))
            else:
                out.append(Outcome(fp, "cross_document", "Declared intake consistent with previous approval", "verified", False,
                                   f"Declared intake {declared}; previously approved {f.effective_value}.", "n/a", rv.severity, v.id,
                                   document_type="previous_approval", field="approved_intake", extracted_value=declared,
                                   expected_value=f.effective_value, method="Numeric comparison", evidence=ev))
        sc = _record_source(ctx, "aicte_records", aicte_records.check_previous_approval(
            {"reference": (ctx.first(v, "certificate_number").effective_value if ctx.first(v, "certificate_number") else "")}),
            "previous_approval", {"reference": ctx.first(v, "certificate_number").effective_value if ctx.first(v, "certificate_number") else ""}, v.id)
        out.append(Outcome(f"ext:aicte:doc{d.id}", "external", "Previous approval: AICTE records not connected", sc.status, False,
                           sc.explanation, "n/a", "low", v.id, document_type="previous_approval", method="AICTE records adapter",
                           evidence=[{"type": "source_check", "source_check_id": sc.id, "source": sc.source_name, "mode": sc.mode}],
                           source_check_id=sc.id))
    return out


def faculty_qualification(ctx: Ctx, rv: RuleVersion) -> list[Outcome]:
    out = []
    certs: dict[str, tuple[Document, DocumentVersion]] = {}
    for d, v in ctx.of_type("qualification_certificate"):
        h = ctx.first(v, "holder_name")
        if h:
            key = X.norm_person(h.effective_value) if h.confirmed_value is not None else h.normalized_value
            certs[key] = (d, v)
    for d, v in ctx.of_type("faculty_list"):
        groups: dict[str, dict] = {}
        for f in v.fields:
            if f.field_name.startswith("faculty_"):
                groups.setdefault(f.group_key, {})[f.field_name] = f
        for fid, g in groups.items():
            nf, qf = g.get("faculty_name"), g.get("faculty_qualification")
            if not nf or not qf:
                continue
            fp = f"faculty:{fid}"
            name = nf.effective_value
            key = X.norm_person(name)
            match = certs.get(key)
            if not match:
                # tolerate initials ordering differences
                for k, val in certs.items():
                    if SequenceMatcher(None, k, key).ratio() >= 0.92:
                        match = val
                        break
            if not match:
                out.append(Outcome(
                    fp, "cross_document", f"No qualification evidence: {name}", "missing", True,
                    f"{name} ({fid}) is listed with qualification '{qf.effective_value}', but no qualification certificate naming this person was found.",
                    "confirmed", rv.severity, v.id, document_type="qualification_certificate", field="faculty_qualification",
                    extracted_value=qf.effective_value, expected_value="Supporting qualification certificate",
                    method="Name linkage between faculty list and certificates", evidence=[ev_field(d, v, nf), ev_field(d, v, qf), ev_rule(rv)],
                    recommended_action="Request the qualification certificate for this faculty member.",
                    institution_text=f"No qualification certificate was submitted for {name} ({fid}), listed with '{qf.effective_value}'.",
                ))
                continue
            cd, cv = match
            deg = ctx.first(cv, "degree")
            claimed = X.degree_level(qf.effective_value)
            found = X.degree_level(deg.effective_value) if deg else "Unknown"
            ev = [ev_field(d, v, nf), ev_field(d, v, qf)] + ([ev_field(cd, cv, deg)] if deg else [ev_doc(cd, cv)]) + [ev_rule(rv)]
            if not deg or found == "Unknown":
                out.append(Outcome(fp, "cross_document", f"Qualification unclear on certificate: {name}", "manual_review", True,
                                   "A certificate naming this person was found, but the degree could not be determined from it.",
                                   "inconclusive", rv.severity, v.id, cv.id, "faculty_list", "degree", qf.effective_value,
                                   deg.effective_value if deg else "(not found)", "Degree-level comparison", evidence=ev,
                                   recommended_action="Inspect the certificate and record an observation."))
            elif claimed != found:
                out.append(Outcome(
                    fp, "cross_document", f"Qualification conflict: {name}", "mismatch", True,
                    f"The faculty list records '{qf.effective_value}' ({claimed}) for {name}, while the supporting certificate {doc_label(cd)} "
                    f"records '{deg.effective_value}' ({found}). The system does not assume which record is correct.",
                    "confirmed", rv.severity, v.id, cv.id, "faculty_list", "faculty_qualification", qf.effective_value,
                    deg.effective_value, "Degree-level comparison across documents", evidence=ev,
                    recommended_action="Request clarification and the certificate for the claimed qualification.",
                    institution_text=f"The qualification listed for {name} ('{qf.effective_value}') differs from the submitted certificate ('{deg.effective_value}').",
                ))
            else:
                out.append(Outcome(fp, "cross_document", f"Qualification supported: {name}", "verified", False,
                                   f"Faculty list and certificate both indicate {claimed}.", "n/a", rv.severity, v.id, cv.id,
                                   "faculty_list", "faculty_qualification", qf.effective_value, deg.effective_value,
                                   "Degree-level comparison across documents", evidence=ev))
    return out


# ------------------------------------------------------------------ external sources


def _record_source(ctx: Ctx, code: str, res, claim_type: str, claim: dict, dv_id: int | None) -> SourceCheck:
    src = ctx.sources.get(code)
    sc = SourceCheck(
        run_id=ctx.run.id, application_id=ctx.app.id, source_code=code,
        source_name=src.name if src else code, source_type=src.source_type if src else "",
        mode=res.mode, claim_type=claim_type, claim=claim, query=res.query, status=res.status,
        http_status=res.http_status, response_summary=res.response_summary, fields_compared=res.fields_compared,
        explanation=res.explanation, reference_url=res.reference_url, document_version_id=dv_id, duration_ms=res.duration_ms,
    )
    ctx.db.add(sc)
    ctx.db.flush()
    return sc


def _publications(ctx: Ctx):
    for d, v in ctx.of_type("publication_list"):
        groups: dict[str, dict] = {}
        for f in v.fields:
            if f.field_name.startswith("pub_"):
                groups.setdefault(f.group_key, {})[f.field_name] = f
        for gk, g in sorted(groups.items()):
            yield d, v, gk, g


def publication_metadata(ctx: Ctx, rv: RuleVersion) -> list[Outcome]:
    out = []
    src = ctx.sources.get("crossref")
    mode = src.mode if src else "disabled"
    for d, v, gk, g in _publications(ctx):
        claim = {k: (g[f"pub_{k}"].effective_value if f"pub_{k}" in g else "") for k in ("title", "authors", "venue", "year", "doi")}
        res = crossref.check_publication(claim, mode, timeout=src.timeout_seconds if src else None)
        sc = _record_source(ctx, "crossref", res, "publication_metadata", claim, v.id)
        key = claim["doi"].lower() or gk
        title_short = (claim["title"][:70] + "…") if len(claim["title"]) > 70 else claim["title"]
        ev = [ev_field(d, v, f) for f in g.values() if f.field_name in ("pub_title", "pub_authors", "pub_doi", "pub_year")]
        ev += [{"type": "source_check", "source_check_id": sc.id, "source": sc.source_name, "mode": sc.mode, "status": sc.status}, ev_rule(rv)]
        status = res.status
        is_issue = status in ("mismatch", "manual_review")
        out.append(Outcome(
            f"pubmeta:{key}", "external", f"Publication metadata — {title_short}", status, is_issue,
            res.explanation, {"verified": "confirmed", "mismatch": "confirmed"}.get(status, "inconclusive"), rv.severity, v.id,
            document_type="publication_list", field="publication metadata", extracted_value=f"{claim['title']} ({claim['year']}) DOI {claim['doi']}",
            expected_value="Crossref record for DOI", method=f"Crossref connector ({res.mode})", limitations=crossref.LIMITS,
            evidence=ev, source_check_id=sc.id,
            recommended_action={"mismatch": "Ask the institution to confirm the citation details and authorship.",
                                "manual_review": "Examine the publication evidence manually.",
                                "source_unavailable": "Re-run verification when the source is reachable, or verify manually.",
                                "simulated": "Simulated result — verify against a live source before relying on it."}.get(status, ""),
            institution_text=(f"The details submitted for the publication '{title_short}' (DOI {claim['doi']}) do not match the DOI registration record."
                              if status == "mismatch" else f"Please provide verifiable details (DOI, publisher link) for the publication '{title_short}'."),
        ))
    return out


def publication_indexing(ctx: Ctx, rv: RuleVersion) -> list[Outcome]:
    out = []
    target = rv.params.get("index", "Scopus").lower()
    src = ctx.sources.get("scopus")
    mode = src.mode if src else "disabled"
    for d, v, gk, g in _publications(ctx):
        idx = g.get("pub_indexing")
        if not idx or target not in idx.effective_value.lower():
            continue
        claim = {k: (g[f"pub_{k}"].effective_value if f"pub_{k}" in g else "") for k in ("title", "doi")}
        claim["claimed_index"] = idx.effective_value
        res = scopus.check_indexing(claim, mode)
        sc = _record_source(ctx, "scopus", res, "publication_indexing", claim, v.id)
        key = (claim["doi"] or gk).lower()
        title_short = (claim["title"][:70] + "…") if len(claim["title"]) > 70 else claim["title"]
        ev = [ev_field(d, v, idx)] + [ev_field(d, v, g[k]) for k in ("pub_title", "pub_doi") if k in g]
        ev += [{"type": "source_check", "source_check_id": sc.id, "source": sc.source_name, "mode": sc.mode, "status": sc.status}, ev_rule(rv)]
        if res.status == "verified":
            status, issue, reason = "verified", False, res.explanation
        elif res.status == "source_unavailable":
            status, issue = "manual_review", True
            reason = ("Indexing could not be verified. Submitted claim: indexed in " + idx.effective_value + ". " + res.explanation +
                      " Status is Manual Review Required — this is not a confirmed mismatch.")
        else:
            status, issue, reason = res.status, True, res.explanation
        out.append(Outcome(
            f"pubindex:{key}", "external", f"Indexing claim ({rv.params.get('index', 'Scopus')}) — {title_short}", status, issue, reason,
            "inconclusive" if status != "verified" else "confirmed", rv.severity, v.id, document_type="publication_list",
            field="claimed indexing", extracted_value=idx.effective_value, expected_value=f"{rv.params.get('index', 'Scopus')} record",
            method=f"Scopus connector ({res.mode})", evidence=ev, source_check_id=sc.id,
            limitations="Only an authorised Scopus record establishes Scopus indexing. Crossref metadata does not.",
            recommended_action="Request an authoritative indexing record (e.g. Scopus source/record page) or other acceptable evidence.",
            institution_text=f"The claim that '{title_short}' is indexed in {rv.params.get('index', 'Scopus')} could not be verified. Provide authoritative indexing evidence.",
        ))
    return out


# ------------------------------------------------------------------ duplicates & anomalies


def duplicates(ctx: Ctx, rv: RuleVersion) -> list[Outcome]:
    from sqlalchemy import select

    from ...models import Application

    out = []
    max_ham = int(rv.params.get("image_max_hamming", 5))
    text_thr = float(rv.params.get("text_jaccard", 0.92))
    items = ctx.docs
    for i, (d1, v1) in enumerate(items):
        for d2, v2 in items[i + 1:]:
            fp = f"dup:doc{min(d1.id, d2.id)}-doc{max(d1.id, d2.id)}"
            ev = [ev_doc(d1, v1, f"SHA-256 {v1.sha256[:16]}…"), ev_doc(d2, v2, f"SHA-256 {v2.sha256[:16]}…"), ev_rule(rv)]
            if v1.sha256 == v2.sha256:
                out.append(Outcome(
                    fp, "duplicate", f"Identical file submitted twice: {d1.title} / {d2.title}", "manual_review", True,
                    f"{doc_label(d1)} and {doc_label(d2)} have the same SHA-256 hash, i.e. they are byte-for-byte the same file.",
                    "confirmed", rv.severity, v1.id, v2.id, d1.document_type, "file hash", v1.sha256, v2.sha256,
                    "SHA-256 exact match", evidence=ev,
                    limitations="An identical file is a fact; whether it is improper (e.g. one photo used for two facilities) needs reviewer judgement.",
                    recommended_action="Check whether the same evidence was used for two different claims.",
                    institution_text=f"The same file was submitted as both '{d1.title}' and '{d2.title}'. Submit distinct evidence for each item.",
                ))
            elif v1.image_hash and v2.image_hash and X.hamming(v1.image_hash, v2.image_hash) <= max_ham:
                hd = X.hamming(v1.image_hash, v2.image_hash)
                out.append(Outcome(
                    fp, "duplicate", f"Near-duplicate images: {d1.title} / {d2.title}", "manual_review", True,
                    f"The two images differ by {hd} of 64 bits in their difference hash, suggesting the same scene or a lightly edited copy.",
                    "suspected", rv.severity, v1.id, v2.id, d1.document_type, "image dHash", v1.image_hash, v2.image_hash,
                    f"Perceptual difference hash (Hamming distance {hd} ≤ {max_ham})", evidence=ev,
                    limitations="Perceptual hashes can match visually similar but genuinely different rooms (e.g. identical classrooms).",
                    recommended_action="Compare the images side by side.",
                    institution_text=f"'{d1.title}' and '{d2.title}' appear to show the same image. Submit distinct photographs.",
                ))
            elif v1.extracted_text and v2.extracted_text and d1.document_type == d2.document_type:
                j = X.jaccard(X.shingles(v1.extracted_text), X.shingles(v2.extracted_text))
                if j >= text_thr:
                    out.append(Outcome(fp, "duplicate", f"Near-duplicate text: {d1.title} / {d2.title}", "manual_review", True,
                                       f"The documents share {round(j * 100)}% of 5-word sequences.", "suspected", rv.severity, v1.id, v2.id,
                                       d1.document_type, "text", f"Jaccard {j:.2f}", f"≥ {text_thr}", "5-word shingle Jaccard similarity",
                                       evidence=ev, limitations="Template-based certificates can legitimately share most text.",
                                       recommended_action="Compare both documents."))
    # Same file appearing in another application (reviewer-only finding)
    hashes = {v.sha256: (d, v) for d, v in items}
    if hashes:
        rows = ctx.db.execute(
            select(DocumentVersion, Document, Application)
            .join(Document, DocumentVersion.document_id == Document.id)
            .join(Application, Document.application_id == Application.id)
            .where(DocumentVersion.sha256.in_(list(hashes)), Application.id != ctx.app.id)
        ).all()
        for ov, od, oa in rows:
            d, v = hashes[ov.sha256]
            out.append(Outcome(
                f"dupx:doc{d.id}-app{oa.id}", "duplicate", f"File also submitted in another application: {d.title}", "manual_review", True,
                f"{doc_label(d)} is byte-identical to a document in application {oa.reference} ({oa.institution.name}).",
                "confirmed", "high", v.id, None, d.document_type, "file hash", v.sha256, "", "SHA-256 exact match across applications",
                evidence=[ev_doc(d, v), {"type": "external_application", "application_reference": oa.reference, "document_title": od.title}, ev_rule(rv)],
                limitations="Internal finding — do not disclose the other institution's identity in notices.",
                recommended_action="Investigate why the same file appears in two institutions' submissions.",
                institution_text=f"'{d.title}' could not be accepted as institution-specific evidence. Submit an original document issued to your institution.",
            ))
    return out


def document_anomaly(ctx: Ctx, rv: RuleVersion) -> list[Outcome]:
    out = []
    max_gap_days = int(rv.params.get("metadata_gap_days", 30))
    lim = ("Anomaly indicators are reasons to look closer, not evidence of forgery. Legitimate documents can be re-saved, "
           "stamped or edited for benign reasons. A human examination (and, where appropriate, the issuing authority) must decide.")
    for d, v in ctx.docs:
        if v.mime_type != "application/pdf" or v.processing_status != "processed":
            continue
        q = v.quality or {}
        for i, fo in enumerate(q.get("font_outliers", [])[:3]):
            out.append(Outcome(
                f"anom:font:doc{d.id}:{i}", "anomaly", f"Font inconsistency in key value: {d.title}", "manual_review", True,
                f"The line '{fo['text']}' is set in {', '.join(fo['fonts'])}, while the document body uses {fo['dominant_font']}.",
                "suspected", rv.severity, v.id, document_type=d.document_type, field="typeface", extracted_value=", ".join(fo["fonts"]),
                expected_value=fo["dominant_font"], method="PDF font span analysis (PyMuPDF)",
                evidence=[ev_doc(d, v, "Highlighted line uses a rare font", fo["page"], fo["bbox"]), ev_rule(rv)], limitations=lim,
                recommended_action="Compare with the issuing authority's original; consider requesting a certified copy.",
                institution_text=f"Certain details on '{d.title}' require verification. Submit a certified copy from the issuing authority.",
            ))
        for i, ob in enumerate(q.get("overlay_boxes", [])[:3]):
            out.append(Outcome(
                f"anom:overlay:doc{d.id}:{i}", "anomaly", f"Opaque box over text: {d.title}", "manual_review", True,
                "A white filled rectangle is drawn over a text region. This pattern can hide underlying content.",
                "suspected", rv.severity, v.id, document_type=d.document_type, field="page drawing layer",
                method="PDF drawing-layer inspection", evidence=[ev_doc(d, v, "Region covered by an opaque shape", ob["page"], ob["bbox"]), ev_rule(rv)],
                limitations=lim, recommended_action="Inspect the highlighted region; request a certified copy if doubt remains.",
                institution_text=f"Certain details on '{d.title}' require verification. Submit a certified copy from the issuing authority.",
            ))
        md = v.file_metadata or {}
        cd, mdd = _pdf_date(md.get("creationDate", "")), _pdf_date(md.get("modDate", ""))
        if cd and mdd and (mdd - cd) > timedelta(days=max_gap_days):
            out.append(Outcome(
                f"anom:meta:doc{d.id}", "anomaly", f"File modified long after creation: {d.title}", "manual_review", True,
                f"PDF metadata shows creation on {cd.date()} and modification on {mdd.date()} ({(mdd - cd).days} days later)"
                + (f"; producer '{md.get('producer')}'." if md.get("producer") else "."),
                "suspected", "low", v.id, document_type=d.document_type, field="PDF metadata",
                extracted_value=f"created {cd.date()}, modified {mdd.date()}", method="PDF metadata comparison",
                evidence=[ev_doc(d, v, f"creator={md.get('creator', '')}; producer={md.get('producer', '')}"), ev_rule(rv)],
                limitations=lim + " Metadata is easily changed and frequently updated by ordinary software.",
                recommended_action="Consider together with other indicators; on its own this is weak evidence.",
            ))
    return out


def _pdf_date(s: str):
    from datetime import datetime

    s = (s or "").replace("D:", "")[:14]
    try:
        return datetime.strptime(s, "%Y%m%d%H%M%S")
    except ValueError:
        return None


# ------------------------------------------------------------------ infrastructure


def infrastructure_evidence(ctx: Ctx, rv: RuleVersion) -> list[Outcome]:
    out = []
    min_photos = int(rv.params.get("min_photos", 2))
    photos = ctx.of_type("infrastructure_photo")
    plans = ctx.of_type("floor_plan")
    lim = ("The system checks presence, labels and image quality only. It does not assess room dimensions, equipment or "
           "physical compliance; these require inspection.")
    if len(photos) < min_photos:
        out.append(Outcome("infra:count", "infrastructure", "Insufficient infrastructure photographs", "missing", True,
                           f"{len(photos)} photograph(s) submitted; the configured checklist expects at least {min_photos}.",
                           "confirmed", rv.severity, document_type="infrastructure_photo", field="photo count",
                           extracted_value=str(len(photos)), expected_value=f"≥ {min_photos}", method="Count",
                           evidence=[ev_rule(rv)], limitations=lim,
                           recommended_action="Request the missing photographs.",
                           institution_text=f"At least {min_photos} labelled infrastructure photographs are required; {len(photos)} were submitted."))
    plan_rooms: dict[str, tuple] = {}
    for d, v in plans:
        for f in ctx.fields(v, "floor_room"):
            use = next((x for x in v.fields if x.field_name == "floor_room_use" and x.group_key == f.group_key), None)
            plan_rooms[f.effective_value.upper()] = (d, v, f, use)
    for d, v in photos:
        q = v.quality or {}
        if q.get("blurry") or q.get("low_resolution"):
            out.append(Outcome(f"infra:quality:doc{d.id}", "infrastructure", f"Low-quality photograph: {d.title}", "manual_review", True,
                               f"Image {q.get('width_px')}×{q.get('height_px')} px, sharpness (Laplacian variance) {q.get('sharpness_laplacian_var')}.",
                               "confirmed", "low", v.id, document_type="infrastructure_photo", field="image quality",
                               method="OpenCV sharpness and resolution", evidence=[ev_doc(d, v), ev_rule(rv)], limitations=lim,
                               recommended_action="Request a clearer photograph if it is needed to assess the item.",
                               institution_text=f"The photograph '{d.title}' is too blurred or small to be used as evidence."))
        lab = ctx.first(v, "room_label")
        if not lab:
            out.append(Outcome(f"infra:label:doc{d.id}", "infrastructure", f"No room label visible: {d.title}", "manual_review", True,
                               "No room/facility label (e.g. 'Room: CL-201') could be read from the photograph.", "inconclusive", "low",
                               v.id, document_type="infrastructure_photo", field="room_label", extracted_value="(not found)",
                               method="OCR of photo caption", evidence=[ev_doc(d, v), ev_rule(rv)], limitations=lim,
                               recommended_action="Check the image; ask for labelled photographs if needed.",
                               institution_text=f"The photograph '{d.title}' does not show a readable room label."))
            continue
        room = lab.effective_value.upper()
        use_f = next((x for x in v.fields if x.field_name == "room_label_use"), None)
        if plans and room not in plan_rooms:
            out.append(Outcome(f"infra:room:doc{d.id}", "infrastructure", f"Room {room} not on floor plan", "mismatch", True,
                               f"The photograph is labelled {room}, but the submitted floor plan lists no such room.", "confirmed",
                               rv.severity, v.id, plans[0][1].id, "infrastructure_photo", "room_label", room,
                               "a room listed on the floor plan", "Label cross-reference with floor plan",
                               evidence=[ev_field(d, v, lab), ev_doc(*plans[0][:2]), ev_rule(rv)], limitations=lim,
                               recommended_action="Ask the institution to reconcile photo labels with the floor plan.",
                               institution_text=f"The photograph '{d.title}' is labelled {room}, which does not appear on the submitted floor plan."))
        elif room in plan_rooms:
            pd, pv, pf, puse = plan_rooms[room]
            ev = [ev_field(d, v, lab)] + ([ev_field(d, v, use_f)] if use_f else []) + [ev_field(pd, pv, pf)] + ([ev_field(pd, pv, puse)] if puse else []) + [ev_rule(rv)]
            if use_f and puse and SequenceMatcher(None, X.norm_text(use_f.effective_value), X.norm_text(puse.effective_value)).ratio() < 0.6:
                out.append(Outcome(f"infra:room:doc{d.id}", "infrastructure", f"Facility use differs for {room}", "mismatch", True,
                                   f"Photo caption describes {room} as '{use_f.effective_value}', floor plan lists it as '{puse.effective_value}'.",
                                   "confirmed", rv.severity, v.id, pv.id, "infrastructure_photo", "room use", use_f.effective_value,
                                   puse.effective_value, "Label cross-reference with floor plan", evidence=ev, limitations=lim,
                                   recommended_action="Request clarification; consider physical inspection.",
                                   institution_text=f"Room {room} is described differently in the photograph ('{use_f.effective_value}') and the floor plan ('{puse.effective_value}')."))
            else:
                out.append(Outcome(f"infra:room:doc{d.id}", "infrastructure", f"Room {room} found on floor plan", "verified", False,
                                   "Photo label corresponds to a room on the floor plan (labels only; not a physical verification).",
                                   "n/a", rv.severity, v.id, pv.id, "infrastructure_photo", "room_label", room, room,
                                   "Label cross-reference with floor plan", evidence=ev, limitations=lim))
    return out


CHECKS = {
    "checklist_completeness": checklist_completeness,
    "required_fields": required_fields,
    "validity": validity,
    "extraction_quality": extraction_quality,
    "field_consistency": field_consistency,
    "intake_consistency": intake_consistency,
    "faculty_qualification": faculty_qualification,
    "publication_metadata": publication_metadata,
    "publication_indexing": publication_indexing,
    "duplicates": duplicates,
    "document_anomaly": document_anomaly,
    "infrastructure_evidence": infrastructure_evidence,
}
