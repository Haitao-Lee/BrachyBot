const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=process.argv[2]||path.resolve(__dirname,'../web/app/static/js');
const read=n=>fs.readFileSync(path.join(root,n),'utf8');
const shell=read('brachybot-report-shell.js'),chat=read('brachybot-chat-core.js'),todo=read('brachybot-chat-todo.js');
const start=shell.indexOf('function reportCaptureFailureMessage(');
const c=vm.createContext({});vm.runInContext(shell.slice(start,shell.indexOf('\n}',start)+2),c);
assert.match(c.reportCaptureFailureMessage({missing:['report_fig1_global','report_fig2_axial']},'zh'),/缺少：Fig 1\(a\), Fig 2\(a\)/);
assert.match(c.reportCaptureFailureMessage({},'en'),/Previous figures were retained/);
const begin=chat.indexOf('const _INLINE_ICON_RULES =');
vm.runInContext(chat.slice(begin,chat.indexOf('\n];',begin)+3)+'\nglobalThis.rules=_INLINE_ICON_RULES;',c);
// First matching rule must describe failure, not the word success in a negation.
const message='报告重新生成未完成。不能把本次操作报告为成功。';
assert.match(JSON.stringify(c.rules.find(r=>r.re.test(message))),/⚠/);
assert(!todo.includes('if ((turnFailed || turnCancelled)'));
assert(todo.includes("failedAction?.stage === 'report_capture'"));
console.log('PASS: localized missing slots, truthful capture failure and negative status icon');
