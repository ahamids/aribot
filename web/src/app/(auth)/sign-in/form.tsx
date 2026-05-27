"use client";

import { useActionState } from "react";
import { signIn } from "@/app/actions/auth";

export function SignInForm() {
  const [state, action, pending] = useActionState(signIn, undefined);

  return (
    <form action={action} className="flex flex-col gap-4">
      <Field
        label="Email"
        name="email"
        type="email"
        required
        autoComplete="email"
        errors={state?.errors?.email}
      />
      <Field
        label="Password"
        name="password"
        type="password"
        required
        autoComplete="current-password"
        errors={state?.errors?.password}
      />

      {state?.message && (
        <div className="outline-plum rounded-[12px] bg-cream-deep text-plum px-4 py-3 text-sm">
          <span aria-hidden className="mr-1.5 font-black">⚠</span>
          {state.message}
        </div>
      )}

      <button
        type="submit"
        disabled={pending}
        className="sticker outline-plum-thick rounded-[18px] bg-coral text-plum px-6 py-3.5 text-lg font-black mt-2 disabled:opacity-60 disabled:translate-y-0 transition hover:translate-y-[-2px]"
      >
        {pending ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}

function Field({
  label,
  errors,
  ...props
}: {
  label: string;
  errors?: string[];
} & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className="flex flex-col gap-1.5">
      <label
        htmlFor={props.name}
        className="text-sm font-bold uppercase tracking-wide text-plum-mid"
      >
        {label}
      </label>
      <input
        id={props.name}
        {...props}
        className="outline-plum rounded-[12px] bg-paper text-plum px-4 py-3 text-base placeholder:text-plum-soft focus:outline-none focus:ring-2 focus:ring-coral focus:border-transparent"
      />
      {errors && errors.length > 0 && (
        <p className="text-sm text-pnl-red">{errors[0]}</p>
      )}
    </div>
  );
}
