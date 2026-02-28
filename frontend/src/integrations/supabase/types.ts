export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  // Allows to automatically instantiate createClient with right options
  // instead of createClient<Database, { PostgrestVersion: 'XX' }>(URL, KEY)
  __InternalSupabase: {
    PostgrestVersion: "14.1"
  }
  public: {
    Tables: {
      agent_runs: {
        Row: {
          agent_name: string
          agent_run_id: string
          created_at: string
          dispute_id: string | null
          error_text: string | null
          input_json: Json
          output_json: Json
          status: string
          step_name: string
        }
        Insert: {
          agent_name: string
          agent_run_id?: string
          created_at?: string
          dispute_id?: string | null
          error_text?: string | null
          input_json?: Json
          output_json?: Json
          status: string
          step_name: string
        }
        Update: {
          agent_name?: string
          agent_run_id?: string
          created_at?: string
          dispute_id?: string | null
          error_text?: string | null
          input_json?: Json
          output_json?: Json
          status?: string
          step_name?: string
        }
        Relationships: [
          {
            foreignKeyName: "agent_runs_dispute_id_fkey"
            columns: ["dispute_id"]
            isOneToOne: false
            referencedRelation: "disputes"
            referencedColumns: ["dispute_id"]
          },
        ]
      }
      approvals: {
        Row: {
          approval_id: string
          channel: string | null
          created_at: string
          decision: string
          dispute_id: string | null
          note: string | null
          user_id: string | null
        }
        Insert: {
          approval_id?: string
          channel?: string | null
          created_at?: string
          decision: string
          dispute_id?: string | null
          note?: string | null
          user_id?: string | null
        }
        Update: {
          approval_id?: string
          channel?: string | null
          created_at?: string
          decision?: string
          dispute_id?: string | null
          note?: string | null
          user_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "approvals_dispute_id_fkey"
            columns: ["dispute_id"]
            isOneToOne: false
            referencedRelation: "disputes"
            referencedColumns: ["dispute_id"]
          },
          {
            foreignKeyName: "approvals_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "users"
            referencedColumns: ["user_id"]
          },
        ]
      }
      case_events: {
        Row: {
          actor: string | null
          case_id: string | null
          created_at: string | null
          details: Json | null
          event_type: string | null
          id: string
        }
        Insert: {
          actor?: string | null
          case_id?: string | null
          created_at?: string | null
          details?: Json | null
          event_type?: string | null
          id?: string
        }
        Update: {
          actor?: string | null
          case_id?: string | null
          created_at?: string | null
          details?: Json | null
          event_type?: string | null
          id?: string
        }
        Relationships: [
          {
            foreignKeyName: "case_events_case_id_fkey"
            columns: ["case_id"]
            isOneToOne: false
            referencedRelation: "cases"
            referencedColumns: ["id"]
          },
        ]
      }
      cases: {
        Row: {
          booking_reference: string | null
          category: string | null
          compute_cost: number | null
          created_at: string | null
          decision_json: Json | null
          draft_email_body: string | null
          draft_email_subject: string | null
          eligibility_result: string | null
          email_body: string | null
          email_subject: string | null
          estimated_value: number | null
          fee_amount: number | null
          flight_number: string | null
          form_data: Json | null
          from_email: string | null
          id: string
          incident_date: string | null
          invoice_id: string | null
          invoice_url: string | null
          message_id: string | null
          recovered_amount: number | null
          source: string | null
          status: string | null
          stripe_checkout_session_id: string | null
          stripe_checkout_url: string | null
          thread_id: string | null
          to_email: string | null
          updated_at: string | null
          vendor: string | null
        }
        Insert: {
          booking_reference?: string | null
          category?: string | null
          compute_cost?: number | null
          created_at?: string | null
          decision_json?: Json | null
          draft_email_body?: string | null
          draft_email_subject?: string | null
          eligibility_result?: string | null
          email_body?: string | null
          email_subject?: string | null
          estimated_value?: number | null
          fee_amount?: number | null
          flight_number?: string | null
          form_data?: Json | null
          from_email?: string | null
          id?: string
          incident_date?: string | null
          invoice_id?: string | null
          invoice_url?: string | null
          message_id?: string | null
          recovered_amount?: number | null
          source?: string | null
          status?: string | null
          stripe_checkout_session_id?: string | null
          stripe_checkout_url?: string | null
          thread_id?: string | null
          to_email?: string | null
          updated_at?: string | null
          vendor?: string | null
        }
        Update: {
          booking_reference?: string | null
          category?: string | null
          compute_cost?: number | null
          created_at?: string | null
          decision_json?: Json | null
          draft_email_body?: string | null
          draft_email_subject?: string | null
          eligibility_result?: string | null
          email_body?: string | null
          email_subject?: string | null
          estimated_value?: number | null
          fee_amount?: number | null
          flight_number?: string | null
          form_data?: Json | null
          from_email?: string | null
          id?: string
          incident_date?: string | null
          invoice_id?: string | null
          invoice_url?: string | null
          message_id?: string | null
          recovered_amount?: number | null
          source?: string | null
          status?: string | null
          stripe_checkout_session_id?: string | null
          stripe_checkout_url?: string | null
          thread_id?: string | null
          to_email?: string | null
          updated_at?: string | null
          vendor?: string | null
        }
        Relationships: []
      }
      disputes: {
        Row: {
          category: string
          created_at: string
          dispute_id: string
          draft_payload_json: Json | null
          latest_reason: string | null
          policy_region: string
          status: string
          updated_at: string
          user_id: string | null
          vendor_name: string | null
        }
        Insert: {
          category: string
          created_at?: string
          dispute_id?: string
          draft_payload_json?: Json | null
          latest_reason?: string | null
          policy_region?: string
          status: string
          updated_at?: string
          user_id?: string | null
          vendor_name?: string | null
        }
        Update: {
          category?: string
          created_at?: string
          dispute_id?: string
          draft_payload_json?: Json | null
          latest_reason?: string | null
          policy_region?: string
          status?: string
          updated_at?: string
          user_id?: string | null
          vendor_name?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "disputes_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "users"
            referencedColumns: ["user_id"]
          },
        ]
      }
      messages: {
        Row: {
          body_text: string | null
          created_at: string
          direction: string
          dispute_id: string | null
          external_message_id: string
          message_id: string
          payload_json: Json
          received_at: string | null
          source: string
          subject: string | null
          thread_id: string | null
          user_id: string | null
        }
        Insert: {
          body_text?: string | null
          created_at?: string
          direction: string
          dispute_id?: string | null
          external_message_id: string
          message_id?: string
          payload_json?: Json
          received_at?: string | null
          source: string
          subject?: string | null
          thread_id?: string | null
          user_id?: string | null
        }
        Update: {
          body_text?: string | null
          created_at?: string
          direction?: string
          dispute_id?: string | null
          external_message_id?: string
          message_id?: string
          payload_json?: Json
          received_at?: string | null
          source?: string
          subject?: string | null
          thread_id?: string | null
          user_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "messages_dispute_id_fkey"
            columns: ["dispute_id"]
            isOneToOne: false
            referencedRelation: "disputes"
            referencedColumns: ["dispute_id"]
          },
          {
            foreignKeyName: "messages_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "users"
            referencedColumns: ["user_id"]
          },
        ]
      }
      terms_cond: {
        Row: {
          confirmation_sent: boolean | null
          terms_cond: boolean | null
          user_email: string
          user_id: string
        }
        Insert: {
          confirmation_sent?: boolean | null
          terms_cond?: boolean | null
          user_email: string
          user_id?: string
        }
        Update: {
          confirmation_sent?: boolean | null
          terms_cond?: boolean | null
          user_email?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "fk_terms_user"
            columns: ["user_id"]
            isOneToOne: true
            referencedRelation: "users"
            referencedColumns: ["user_id"]
          },
        ]
      }
      users: {
        Row: {
          created_at: string
          display_name: string
          email: string
          supabase_auth_user_id: string | null
          user_id: string
        }
        Insert: {
          created_at?: string
          display_name: string
          email: string
          supabase_auth_user_id?: string | null
          user_id?: string
        }
        Update: {
          created_at?: string
          display_name?: string
          email?: string
          supabase_auth_user_id?: string | null
          user_id?: string
        }
        Relationships: []
      }
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      [_ in never]: never
    }
    Enums: {
      [_ in never]: never
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  public: {
    Enums: {},
  },
} as const
