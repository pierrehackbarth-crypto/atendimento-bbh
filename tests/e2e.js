// Teste de ponta a ponta no navegador (Chromium com microfone simulado). Servidor em modo OPENAI_FAKE.
const { chromium } = require('playwright'); const fs = require('fs');
const BASE = process.env.BASE || 'http://127.0.0.1:8899';
(async () => {
  const b = await chromium.launch({ args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] });
  const ctx = await b.newContext({ permissions: ['microphone'] }); const p = await ctx.newPage(); const errs = [];
  p.on('pageerror', e => errs.push(e.message));
  const log = (...a) => console.log(...a);
  await p.goto(BASE); await p.fill('#lEmail', 'a@x.com'); await p.fill('#lPw', 'senha-segura-1'); await p.click('#loginF button');
  await p.waitForSelector('#q'); await p.fill('#q', 'Maria E2E'); await p.click('#novoCli');
  await p.waitForSelector('#novoAt'); await p.click('#novoAt'); await p.waitForSelector('#consent');
  log('start desabilitado sem consentimento:', await p.isDisabled('#bStart'));
  await p.check('#consent'); await p.waitForFunction(() => !document.querySelector('#bStart').disabled);
  await p.click('#bStart'); await p.waitForTimeout(2500); await p.click('#bPause'); const t1 = await p.textContent('#timer'); await p.waitForTimeout(1200);
  log('pausa congela o tempo:', t1 === await p.textContent('#timer'));
  await p.click('#bResume'); await p.waitForTimeout(1200); await p.click('#bStop');
  await p.waitForFunction(() => /1 parte/.test(document.body.innerText), null, { timeout: 15000 }); log('parte de áudio enviada: ok');
  // arrastar e soltar documento
  const pdf = fs.readFileSync(process.env.PDF);
  await p.evaluate(b => { const dt = new DataTransfer(); dt.items.add(new File([Uint8Array.from(b)], 'cnis.pdf', { type: 'application/pdf' }));
    const el = document.querySelector('#drop'); el.dispatchEvent(new DragEvent('dragover', { bubbles: true, dataTransfer: dt })); el.dispatchEvent(new DragEvent('drop', { bubbles: true, dataTransfer: dt })); }, Array.from(pdf));
  await p.waitForSelector('text=cnis.pdf'); log('documento por arrastar: ok');
  // seleção pelo botão
  await p.setInputFiles('#fAttach', { name: 'laudo.png', mimeType: 'image/png', buffer: fs.readFileSync(process.env.PNG) });
  await p.waitForSelector('text=laudo.png'); log('documento por seleção: ok');
  await p.setInputFiles('#fAttach', { name: 'virus.exe', mimeType: 'application/octet-stream', buffer: Buffer.from('MZ') });
  log('anexo inválido recusado:', (await p.textContent('#toast')).includes('formato não aceito'));
  await p.click('[data-a="transcribe"]'); await p.waitForSelector('#trRev', { timeout: 20000 }); log('transcrição: ok');
  await p.click('[data-a="analyze"]'); await p.waitForFunction(() => /analisado/.test(document.body.innerText) && !/analisando/.test(document.body.innerText), null, { timeout: 20000 });
  await p.click('[data-a="generate"]'); await p.waitForSelector('text=Ficha para revisão do advogado', { timeout: 20000 });
  log('divergência com fontes:', await p.evaluate(() => { const s = [...document.querySelectorAll('.fsec')].find(x => x.innerText.startsWith('Divergências')); return !!s && /T001/.test(s.innerText) && /cnis\.pdf p\.1/.test(s.innerText); }));
  await p.fill('[data-fk="motivo_consulta"]', 'Editado pelo advogado'); await p.click('[data-a="save"]'); await p.waitForTimeout(300);
  await p.click('[data-a="generate"]'); await p.waitForSelector('text=Há uma versão mais nova da IA', { timeout: 20000 });
  log('edição preservada após reprocessar:', await p.inputValue('[data-fk="motivo_consulta"]') === 'Editado pelo advogado');
  await p.screenshot({ path: process.env.SHOT || '/tmp/e2e.png', fullPage: true });
  await p.click('[data-a="finalize"]'); await p.check('#cfDel'); await p.click('#cfOk');
  await p.waitForSelector('text=Ficha final', { timeout: 10000 }); log('finalizado; áudio:', await p.evaluate(() => /Áudio excluído/.test(document.body.innerText)));
  // microfone negado
  const ctx2 = await b.newContext(); const p2 = await ctx2.newPage();
  await p2.addInitScript(() => { navigator.mediaDevices.getUserMedia = () => Promise.reject(Object.assign(new Error('x'), { name: 'NotAllowedError' })); });
  await p2.goto(BASE); await p2.fill('#lEmail', 'a@x.com'); await p2.fill('#lPw', 'senha-segura-1'); await p2.click('#loginF button'); await p2.waitForSelector('#q');
  await p2.click('.list a'); await p2.click('#novoAt'); await p2.check('#consent'); await p2.waitForFunction(() => !document.querySelector('#bStart').disabled);
  await p2.click('#bStart'); await p2.waitForSelector('text=Permissão do microfone negada'); log('microfone negado tratado: ok');
  // outro usuário não acessa
  const ctx3 = await b.newContext(); const p3 = await ctx3.newPage(); await p3.goto(BASE); await p3.fill('#lEmail', 'b@x.com'); await p3.fill('#lPw', 'senha-segura-2'); await p3.click('#loginF button'); await p3.waitForSelector('#q');
  const url = p.url(); await p3.goto(url); await p3.waitForTimeout(800); log('usuário B bloqueado:', /não encontrado/i.test(await p3.textContent('#view')));
  log(errs.join('\n') || 'sem erros de página'); await b.close();
})().catch(e => { console.error('FALHA', e.message); process.exit(1); });
