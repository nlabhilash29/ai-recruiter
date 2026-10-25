import { render, screen } from '@testing-library/react';
import App from './App';

test('renders the interview navigation', () => {
  render(<App />);
  expect(screen.getByRole('button', { name: 'Mock Interview' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Recruiter Dashboard' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Video Interview' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Create Mock Interview' })).toBeDisabled();
});
