// Optional adapter for hosts where /dev/null is not writable.
// Keep the same child command; drain discarded streams through pipes instead.
const cp = require('node:child_process');
const spawn = cp.spawn;
cp.spawn = function(command, args, options) {
  const stdio = options && options.stdio;
  if (!Array.isArray(stdio) || !stdio.includes('ignore')) {
    return spawn.apply(this, arguments);
  }
  const child = spawn.call(this, command, args, {
    ...options, stdio: stdio.map(mode => mode === 'ignore' ? 'pipe' : mode),
  });
  stdio.forEach((mode, index) => {
    if (mode !== 'ignore' || !child.stdio[index]) return;
    if (index === 0) child.stdio[index].end();
    else child.stdio[index].resume();
  });
  return child;
};
require('node:module').syncBuiltinESMExports();
