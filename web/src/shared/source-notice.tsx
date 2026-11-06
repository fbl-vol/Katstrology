const repository = 'https://github.com/fbl-vol/Katstrology';
const license = 'https://www.gnu.org/licenses/agpl-3.0.html';

export function SourceNotice() {
  return <p className="source-notice">© 2026 Kat contributors. Original application code is
    licensed under AGPLv3 only, without warranty; you may share and modify it under that license.
    {' '}<a href={repository} target="_blank" rel="noopener noreferrer">Source and build instructions</a>
    {' · '}<a href={license} target="_blank" rel="noopener noreferrer">Read the license</a>
  </p>;
}
