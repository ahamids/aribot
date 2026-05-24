import { z } from "zod";

/**
 * Sign-up / sign-in form validation.
 *
 * Password policy mirrors the Expo app (app/app/(auth)/sign-up.tsx): minimum
 * 12 chars. We deliberately don't enforce character-class rules — NIST
 * SP 800-63B v4 recommends length over complexity. Supabase ALSO enforces
 * server-side checks (configured via the dashboard), so this client-side
 * check is purely a UX nicety.
 */
export const SignUpSchema = z.object({
  email: z.email({ error: "Enter a valid email address." }).trim(),
  password: z
    .string()
    .min(12, { error: "Password must be at least 12 characters." })
    .max(72, { error: "Password too long (bcrypt limit is 72 bytes)." }),
  encryptionAck: z.literal("on", {
    error:
      "You must acknowledge that lost passphrase = lost vault access.",
  }),
});

export const SignInSchema = z.object({
  email: z.email({ error: "Enter a valid email address." }).trim(),
  password: z
    .string()
    .min(1, { error: "Password required." })
    .max(72, { error: "Password too long." }),
});

export type SignUpFormState =
  | {
      errors?: {
        email?: string[];
        password?: string[];
        encryptionAck?: string[];
      };
      message?: string;
    }
  | undefined;

export type SignInFormState =
  | {
      errors?: {
        email?: string[];
        password?: string[];
      };
      message?: string;
    }
  | undefined;
