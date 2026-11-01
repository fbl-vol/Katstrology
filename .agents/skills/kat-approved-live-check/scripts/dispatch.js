async (page) => {
  const send = page.getByRole('button', { name: 'Send message', exact: true });
  if (await send.count() !== 1 || !(await send.isEnabled())) throw new Error('Send button is not uniquely ready');
  await send.click({ timeout: 10000, noWaitAfter: true });
  return 'KAT_META:{"dispatch":"clicked-once"}';
}
