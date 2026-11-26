import re

from src.reasoning.llm_client import LLMClient

REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "rewritten_query": {"type": "string"},
        "vehicle_type": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "expand_query": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
    },
    "required": ["rewritten_query", "vehicle_type", "expand_query"],
}


class LLMQueryProcessor:
    def __init__(self, client=None):
        self.client = client or LLMClient()

        self.system_prompt = """Bạn là bộ tiền xử lý truy vấn cho hệ thống tra cứu luật giao thông Việt Nam.

        Nhiệm vụ:
        - Đọc câu hỏi tự nhiên của người dùng.
        - Viết lại thành 1 truy vấn ngắn, rõ, sát hành vi vi phạm để truy xuất knowledge graph (rewritten_query).
        - Mở rộng truy vấn thành nhiều dạng đồng nghĩa, liệt kê các cụm từ khóa liên quan (expand_query: list các string).
        - Extract vehicle_type nếu có trong query (ví dụ: xe máy, ô tô, xe đạp, phương tiện khác, etc.), nếu không xác định được thì để null.
        - Giữ lại phương tiện, hành vi vi phạm, điều kiện ngữ cảnh nếu có.
        - Không trả lời tư vấn pháp lý.
        - Không giải thích dài dòng.

        Bắt buộc chỉ trả về JSON hợp lệ theo đúng format:
        {"rewritten_query":"...", "vehicle_type": "..." hoặc null, "expand_query": ["...", "...", ...]}
        """

    def rewrite(self, user_query):
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"Câu hỏi: {user_query}"},
        ]
        try:
            return self.client.chat_json(messages, REWRITE_SCHEMA)
        except Exception as e:
            print(f"Lỗi LLM: {e}")
            return {"rewritten_query": user_query, "vehicle_type": None}

    def select_best_result(self, user_query, results):
        if not results:
            return None
        
        # Chuẩn bị danh sách kết quả cho LLM
        results_text = ""
        for i, res in enumerate(results):
            node = res['raw_node']
            results_text += f"{i}. Hành vi: {node.get('description_natural', 'N/A')}\n"
            results_text += f"   Phương tiện: {node.get('vehicle_type', 'N/A')}\n"
            results_text += f"   Mức phạt: {node.get('fine_min', 'N/A')} - {node.get('fine_max', 'N/A')}\n"
            results_text += f"   Trích dẫn: {node.get('legal_basis', 'N/A')}\n\n"
        
        prompt = f"""
        Bạn là chuyên gia pháp luật giao thông Việt Nam.

        Câu hỏi của người dùng:
        {user_query}

        Danh sách kết quả từ hệ thống tìm kiếm:
        {results_text}

        Nhiệm vụ của bạn:
        Chọn **kết quả phù hợp nhất** với câu hỏi của người dùng từ danh sách trên.

        Quy tắc đánh giá:

        1. Ưu tiên **ý nghĩa hành vi vi phạm**, không chỉ so khớp từ khóa.

        2. Người dùng thường nói bằng ngôn ngữ đời thường, trong khi luật dùng ngôn ngữ pháp lý. 
        Hãy nhận diện các cách diễn đạt tương đương.

        Ví dụ:
        - "vượt đèn đỏ", "chạy đèn đỏ", "đi đèn đỏ"
        = "không chấp hành hiệu lệnh của đèn tín hiệu giao thông"

        - "đi sai làn"
        = "đi không đúng phần đường hoặc làn đường"

        - "không dừng xe khi CSGT yêu cầu"
        = "không chấp hành hiệu lệnh của người thi hành công vụ"

        - "không đội mũ bảo hiểm"
        = "không đội mũ bảo hiểm khi điều khiển xe"

        3. Nếu câu hỏi có phương tiện (ví dụ: xe máy) thì **ưu tiên kết quả có cùng phương tiện**, 
        nhưng vẫn có thể chọn phương tiện khác nếu hành vi hoàn toàn giống.

        4. Trong danh sách top kết quả, **hãy luôn cố gắng chọn kết quả gần nghĩa nhất** với câu hỏi.

        5. Chỉ trả về **-1 nếu tất cả kết quả hoàn toàn không liên quan đến hành vi được hỏi**.

        Kết quả trả về:
        - Chỉ trả về **một số nguyên (0-based index)** tương ứng với kết quả phù hợp nhất.

        Không giải thích.
        Không thêm chữ.
        Chỉ trả về số.
        """
        
        try:
            raw_text = self.client.chat_text([{"role": "user", "content": prompt}])
            found = re.search(r"-?\d+", raw_text)
            selected_idx = int(found.group(0)) if found else 0
            if selected_idx == -1:
                # Fallback to first if no match
                return results[0] if results else None
            elif 0 <= selected_idx < len(results):
                return results[selected_idx]
            return results[0]  # Fallback to first
        except Exception as e:
            print(f"Lỗi chọn kết quả: {e}")
            return results[0] if results else None


# Old name, still imported by src/kg/main.py.
GeminiQueryProcessor = LLMQueryProcessor
