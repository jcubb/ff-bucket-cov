/* Node self-test for the Bucket_Report data layer.
 * Extracts the page's <script>, runs the PURE functions in a fake-DOM sandbox,
 * and validates parse / filename-date / merge against the sample CSVs.
 *   run:  node report/_selftest.js   (from the repo root)
 */
"use strict";
const fs = require("fs");
const vm = require("vm");
const path = require("path");

const DIR = __dirname;
const html = fs.readFileSync(path.join(DIR, "Bucket_Report.html"), "utf8");
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if(!m){ console.error("No <script> found"); process.exit(1); }

// Sandbox: a no-op document so the DOMContentLoaded hook never fires initUI.
const sandbox = { document:{ addEventListener(){} }, console };
sandbox.globalThis = sandbox;
vm.runInNewContext(m[1], sandbox, {filename:"Bucket_Report.inline.js"});
const BR = sandbox.__BR;
if(!BR){ console.error("Data layer did not export __BR"); process.exit(1); }

let pass=0, fail=0;
const eq=(got,exp,msg)=>{ const ok = JSON.stringify(got)===JSON.stringify(exp);
  console.log(`${ok?"ok  ":"FAIL"}  ${msg}  ${ok?"":`(got ${JSON.stringify(got)}, want ${JSON.stringify(exp)})`}`);
  ok?pass++:fail++; };

// --- filename date detection ---
eq(BR.detectDateFromName("sample_portfolios_20260331.csv").iso, "2026-03-31", "detect YYYYMMDD");
eq(BR.detectDateFromName("fund_2026-06-30_final.csv").iso, "2026-06-30", "detect YYYY-MM-DD");
eq(BR.detectDateFromName("book_06302026.csv").iso, "2026-06-30", "detect MMDDYYYY");
eq(BR.detectDateFromName("no_date_here.csv"), null, "no date -> null");

// --- load the two sample files ---
const load = f => ({name:f, parsed:BR.parseCSV(fs.readFileSync(path.join(DIR,f),"utf8"))});
const a = load("sample_portfolios_20260331.csv");
const b = load("sample_portfolios_20260630.csv");
eq(a.parsed.rows.length, 39, "date1 rows parsed");
eq(b.parsed.rows.length, 40, "date2 rows parsed");
eq(BR.detectWeightCols(b.parsed.header).length, 15, "15 weight columns detected");
eq(BR.detectDistanceCol(b.parsed.header), "bucket_distance", "distance column detected");

// --- ordering + merge ---
const ord = BR.orderByDate(b, a);           // pass reversed to test auto-ordering
eq(ord.detected, true, "dates detected for ordering");
eq(ord.prior.name, a.name, "prior = earlier date");
eq(ord.current.name, b.name, "current = later date");

const rec = BR.buildRecords(ord.prior, ord.current);
eq(rec.matched.length, 37, "matched funds");
eq(rec.entries.length, 3, "entries (current only)");
eq(rec.exits.length, 2, "exits (prior only)");
eq(rec.ignored.length, 7, "ignored junk columns");
const rising = rec.matched.filter(r=> r.dDist!=null && r.dDist>0).length;
eq(rising, 15, "rising-distance funds");

// spot-check one planted riser (VH0010: 1.25 -> 4.88)
const vh10 = rec.matched.find(r=> r.VehicleCode==="VH0010");
eq(vh10 && vh10.dDist>3, true, "VH0010 flagged as big riser");
// weights present and 15-long
eq(vh10.wCurr.length, 15, "current weight vector length");

// --- parseWeightCols ordering ---
const wm = BR.parseWeightCols(rec.weightCols);
eq(wm.length, 15, "parseWeightCols -> 15");
eq([wm[0].factor, wm[0].bucket], ["value",2], "first bucket = value_2");
eq([wm[14].factor, wm[14].bucket], ["profit",6], "last bucket = profit_6");

// --- buildTree (Deputy -> PM -> Strategy; counts only) ---
const tree = BR.buildTree(rec.matched.concat(rec.entries));
eq(tree.funds, 40, "tree funds = matched + entries");
eq(tree.children.size, 3, "3 deputies");
eq(tree.rising, 15, "tree rising count = matched risers");
const osei = tree.children.get("M. Osei");
eq(!!(osei && osei.children.get("K. Adler")), true, "K. Adler nested under M. Osei");
const adler = osei.children.get("K. Adler");
eq(adler.funds>=3, true, "K. Adler has >=3 funds");

// --- component (marginal-contribution) columns ---
eq(BR.detectComponentCols(b.parsed.header).value, "value_distance", "value_distance detected");
eq(BR.detectComponentCols(b.parsed.header).prof, "prof_distance", "prof_distance detected");
eq(!!rec.componentCols, true, "component cols surfaced on records");
eq(vh10.compCurr.length, 3, "compCurr has 3 factor groups");
const csum = vh10.compCurr.reduce((a,x)=>a+x,0);
eq(Math.abs(csum - vh10.distCurr) < 0.01, true, "compCurr sums to bucket_distance");

console.log(`\n${fail? "SELFTEST FAILED":"ALL SELFTESTS PASSED"}  (${pass} ok, ${fail} failed)`);
process.exit(fail?1:0);
