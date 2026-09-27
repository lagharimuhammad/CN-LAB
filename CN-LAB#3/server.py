import socket
import threading

HOST = '127.0.0.1'
PORT = 5000
LOG_FILE = 'cgpa_log.txt'

log_lock = threading.Lock()

GRADING_SCHEMA = [
    (90, 'A+', 4.00),
    (86, 'A',  4.00),
    (82, 'A-', 3.67),
    (78, 'B+', 3.33),
    (74, 'B',  3.00),
    (70, 'B-', 2.67),
    (66, 'C+', 2.33),
    (62, 'C',  2.00),
    (58, 'C-', 1.67),
    (54, 'D+', 1.33),
    (50, 'D',  1.00),
]


def get_grade_and_gpa(marks):
    """Return (grade, gpa) for the given marks using the FAST schema."""
    for minimum, grade, gpa in GRADING_SCHEMA:
        if marks >= minimum:
            return grade, gpa
    return 'F', 0.00



def send_msg(f, text):
    f.write(f"MSG|{text}\n"); f.flush()


def ask(f, text):
    """Send a question and return the client's answer (None if disconnected)."""
    f.write(f"ASK|{text}\n"); f.flush()
    answer = f.readline()
    if not answer:
        return None
    return answer.strip()


def ask_number(f, text, cast, valid, error):
    """Keep asking until the client sends a valid number."""
    while True:
        raw = ask(f, text)
        if raw is None:
            return None
        try:
            value = cast(raw)
            if valid(value):
                return value
        except ValueError:
            pass
        send_msg(f, error)


def write_log(student_id, subjects, total_ch, cgpa):
    """Append one student's record to the log file (thread-safe)."""
    lines = [f"Student ID: {student_id}"]
    for i, s in enumerate(subjects, 1):
        lines.append(f"Subject {i}: Credit Hours: {s['ch']}, Marks: {s['marks']:g}, "
                     f"Grade: {s['grade']}, GPA: {s['gpa']:.2f}")
    lines.append(f"Total Credit Hours: {total_ch}")
    lines.append(f"Overall CGPA: {cgpa:.2f}")
    lines.append("-" * 60)
    record = "\n".join(lines) + "\n"
    with log_lock:                       
        with open(LOG_FILE, 'a') as log:
            log.write(record)


def handle_client(conn, addr):
    print(f"[+] Client connected: {addr}  (active threads: {threading.active_count()})")
    f = conn.makefile('rw', encoding='utf-8', newline='\n')
    try:
        send_msg(f, "Welcome to FAST-NUCES Karachi Campus CGPA Calculator!")

        student_id = ask(f, "Enter your Student ID: ")
        if not student_id:
            return
        print(f"    {addr} -> Student ID: {student_id}")

        n = ask_number(f, "Enter number of subjects: ", int,
                       lambda v: v > 0, "Invalid input. Enter a whole number greater than 0.")
        if n is None:
            return

        subjects = []
        for i in range(1, n + 1):
            ch = ask_number(f, f"Subject {i} - Credit hours: ", int,
                            lambda v: 1 <= v <= 6,
                            "Invalid credit hours. Enter a whole number from 1 to 6.")
            if ch is None:
                return
            marks = ask_number(f, f"Subject {i} - Marks obtained (out of 100): ", float,
                               lambda v: 0 <= v <= 100,
                               "Invalid marks. Enter a number from 0 to 100.")
            if marks is None:
                return
            grade, gpa = get_grade_and_gpa(marks)
            subjects.append({'ch': ch, 'marks': marks, 'grade': grade, 'gpa': gpa})
            print(f"    {addr} -> Subject {i}: CH={ch}, Marks={marks:g}")

        total_ch = sum(s['ch'] for s in subjects)
        cgpa = sum(s['gpa'] * s['ch'] for s in subjects) / total_ch

        send_msg(f, "")
        send_msg(f, f"Result for {student_id} ")
        for i, s in enumerate(subjects, 1):
            send_msg(f, f"Subject {i}: Credit Hours: {s['ch']}, Marks: {s['marks']:g}, "
                        f"Grade: {s['grade']}, GPA: {s['gpa']:.2f}")
        send_msg(f, f"Total Credit Hours: {total_ch}")
        send_msg(f, f"Overall CGPA: {cgpa:.2f}")

        write_log(student_id, subjects, total_ch, cgpa)
        print(f"[*] {student_id}: CGPA {cgpa:.2f} calculated and logged to {LOG_FILE}")
        f.write("BYE|Thank you for using the CGPA Calculator. Goodbye!\n"); f.flush()
    except (ConnectionError, OSError):
        print(f"[!] Connection lost with {addr}")
    finally:
        try:
            f.close()
        except Exception:
            pass
        conn.close()
        print(f"[-] Client disconnected: {addr}")


def main():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST, PORT))
    server_socket.listen(5)
    print(f"CGPA Server is running on {HOST}:{PORT} ... waiting for students")
    try:
        while True:
            conn, addr = server_socket.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
    except KeyboardInterrupt:
        print("\nServer shutting down.")
    finally:
        server_socket.close()


if __name__ == '__main__':
    main()